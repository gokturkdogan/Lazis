"""Relationship graph endpoints (Phase 7), mounted inside the memory router: the vocabulary,
an entity's relationships (current and past, with how they read from its side), one
relationship with its evidence and the claims it replaced, add / edit / forget, the bounded
neighbourhood for the relation map, and the paths between two entities.

Writes go through ``lazis.memory.relationships`` (the same checks as chat: types must fit the
entity kinds, secrets and instruction-like text are refused, history is kept, forgetting is
suppressed). Sensitive relationships are listed on the entity they belong to — the user's own
data — but never in the map or in paths.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any, TypeVar, cast

from fastapi import APIRouter, Query

from lazis.api.memory_schemas import (
    ForgetResultResponse,
    GraphEdgeModel,
    GraphNeighbourhoodResponse,
    GraphNodeModel,
    GraphPathModel,
    GraphPathsResponse,
    MemoryEvidenceModel,
    MemorySubjectModel,
    RelationshipCreateRequest,
    RelationshipDetailResponse,
    RelationshipEditRequest,
    RelationshipListResponse,
    RelationshipModel,
    RelationshipTypeListResponse,
    RelationshipTypeModel,
    RelationshipWriteResponse,
)
from lazis.memory import graph, relations
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.models import CURRENT, USER_ID, Relationship
from lazis.memory.service import NotFound
from lazis.storage.driver import Connection

T = TypeVar("T")
Q = Callable[[Callable[[Connection], T]], Awaitable[T]]
ENTITY = r"^[0-9A-Za-z_-]{1,64}$"
SHOWN = ("active", "planned", "unverified", "ended", "superseded")


def _subject(conn: Connection, eid: str) -> MemorySubjectModel:
    e = repo.get_entity(conn, eid)
    if e is None:
        raise NotFound("entity not found")
    name = "Kullanıcı" if e.is_user else e.name
    return MemorySubjectModel(id=e.id, kind=e.kind, name=name, relation=e.relation)


def relationship_model(
    conn: Connection, r: Relationship, viewer: str | None = None
) -> RelationshipModel:
    s, t = _subject(conn, r.source_id), _subject(conn, r.target_id)
    other: MemorySubjectModel | None = None
    reading: str | None = None
    hop = graph.reading(r, viewer) if viewer in (r.source_id, r.target_id) else None
    if hop is not None:
        other = t if hop.to == r.target_id else s
        if not hop.inverted:
            reading = relations.TYPES[hop.type].label
        elif relations.TYPES[r.type].inverse_label:
            reading = relations.TYPES[r.type].inverse_label
    rt = relations.TYPES.get(r.type)
    return RelationshipModel(
        id=r.id,
        source=s,
        type=r.type,
        type_label=rt.label if rt else r.type,
        target=t,
        text=relations.describe(s.name, r.type, t.name) if rt else r.type,
        reading=reading,
        other=other,
        status=r.status,
        origin=cast(Any, r.origin),
        confidence=r.confidence,
        sensitivity=r.sensitivity,
        time_text=r.time_text,
        qualifier=r.qualifier,
        valid_from=r.valid_from,
        valid_to=r.valid_to,
        conflict_state=r.conflict_state,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _write_result(r: rels.RelReport) -> RelationshipWriteResponse:
    return RelationshipWriteResponse(
        created=len(r.created),
        updated=len(r.updated),
        ended=len(r.ended),
        superseded=len(r.superseded),
        inbox=len(r.inbox),
        dropped=dict(r.dropped),
    )


def register_graph_routes(router: APIRouter, q: Q[Any]) -> None:
    @router.get("/relationship-types", response_model=RelationshipTypeListResponse)
    async def relationship_types() -> RelationshipTypeListResponse:  # pyright: ignore[reportUnusedFunction]
        return RelationshipTypeListResponse(
            types=[
                RelationshipTypeModel(
                    key=t.key,
                    label=t.label,
                    inverse_label=t.inverse_label,
                    category=t.category,
                    symmetric=t.symmetric,
                    sensitivity=t.sensitivity,
                    source_kinds=list(t.source_kinds),
                    target_kinds=list(t.target_kinds),
                )
                for t in relations.TYPES.values()
            ]
        )

    @router.get("/entities/{entity_id}/relationships", response_model=RelationshipListResponse)
    async def entity_relationships(entity_id: str) -> RelationshipListResponse:  # pyright: ignore[reportUnusedFunction]
        """``entity_id`` may be ``user``: the user's own relationships."""

        def read(c: Connection) -> RelationshipListResponse:
            e = repo.get_entity(c, entity_id)
            if e is None or e.status != "active":
                raise NotFound("entity not found")
            rows = gs.relationships_of(c, e.id, statuses=SHOWN)
            return RelationshipListResponse(
                relationships=[relationship_model(c, r, e.id) for r in rows]
            )

        return await q(read)

    @router.get("/relationships/{rel_id}", response_model=RelationshipDetailResponse)
    async def relationship_detail(rel_id: str) -> RelationshipDetailResponse:  # pyright: ignore[reportUnusedFunction]
        def read(c: Connection) -> RelationshipDetailResponse:
            r = gs.get_relationship(c, rel_id)
            if r is None:
                raise NotFound("relationship not found")
            previous: list[RelationshipModel] = []
            cur = r
            while cur.supersedes_id and len(previous) < 10:
                old = gs.get_relationship(c, cur.supersedes_id)
                if old is None:
                    break
                previous.append(relationship_model(c, old))
                cur = old
            evidence = [
                MemoryEvidenceModel(
                    source_type=cast(Any, st), source_ref=ref, quote=quote, created_at=at
                )
                for st, ref, quote, at in gs.evidence_for(c, r.id)
            ]
            return RelationshipDetailResponse(
                relationship=relationship_model(c, r), evidence=evidence, previous=previous
            )

        return await q(read)

    @router.post("/relationships", response_model=RelationshipWriteResponse)
    async def add_relationship(body: RelationshipCreateRequest) -> RelationshipWriteResponse:  # pyright: ignore[reportUnusedFunction]
        return await q(
            lambda c: _write_result(
                rels.add_relationship(
                    c,
                    source_id=body.source_id,
                    type=body.type,
                    target_id=body.target_id,
                    qualifier=body.qualifier,
                    status=body.status,
                    time_text=body.time_text,
                )
            )
        )

    @router.patch("/relationships/{rel_id}", response_model=RelationshipModel)
    async def edit_relationship(rel_id: str, body: RelationshipEditRequest) -> RelationshipModel:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> RelationshipModel:
            r = rels.edit_relationship(
                c,
                rel_id,
                type=body.type,
                qualifier=body.qualifier,
                status=body.status,
                time_text=body.time_text,
            )
            return relationship_model(c, r)

        return await q(write)

    @router.delete("/relationships/{rel_id}", response_model=ForgetResultResponse)
    async def forget_relationship(rel_id: str) -> ForgetResultResponse:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> ForgetResultResponse:
            if gs.get_relationship(c, rel_id) is None:
                raise NotFound("relationship not found")
            res = rels.forget_relationships(c, [rel_id])
            return ForgetResultResponse(memories=res.relationships, entities=0)

        return await q(write)

    @router.get("/graph/neighbourhood/{entity_id}", response_model=GraphNeighbourhoodResponse)
    async def neighbourhood(  # pyright: ignore[reportUnusedFunction]
        entity_id: str,
        depth: Annotated[int, Query(ge=1, le=2)] = 1,
        past: bool = False,
    ) -> GraphNeighbourhoodResponse:
        def read(c: Connection) -> GraphNeighbourhoodResponse:
            e = repo.get_entity(c, entity_id)
            if e is None or e.status != "active":
                raise NotFound("entity not found")
            statuses = (*CURRENT, "ended") if past else CURRENT
            nodes, edges, truncated = graph.neighbourhood(c, e.id, depth=depth, statuses=statuses)
            out_nodes: list[GraphNodeModel] = []
            for nid, d in nodes.items():
                ent = repo.get_entity(c, nid)
                if ent is not None:
                    out_nodes.append(
                        GraphNodeModel(
                            id=nid,
                            name="Kullanıcı" if ent.is_user else ent.name,
                            kind=ent.kind,
                            is_user=ent.is_user,
                            depth=d,
                        )
                    )
            return GraphNeighbourhoodResponse(
                nodes=out_nodes,
                edges=[
                    GraphEdgeModel(
                        id=r.id,
                        source_id=r.source_id,
                        target_id=r.target_id,
                        type=r.type,
                        label=relations.TYPES[r.type].label,
                        status=r.status,
                    )
                    for r in edges
                ],
                truncated=truncated,
            )

        return await q(read)

    @router.get("/graph/paths", response_model=GraphPathsResponse)
    async def paths(  # pyright: ignore[reportUnusedFunction]
        from_: Annotated[str, Query(alias="from", pattern=ENTITY)] = USER_ID,
        to: Annotated[str, Query(pattern=ENTITY)] = USER_ID,
    ) -> GraphPathsResponse:
        def read(c: Connection) -> GraphPathsResponse:
            for eid in (from_, to):
                e = repo.get_entity(c, eid)
                if e is None or e.status != "active":
                    raise NotFound("entity not found")
            found = graph.paths_between(c, from_, to, limit=graph.MAX_LISTED)
            g = graph.Renderer(c)
            return GraphPathsResponse(
                paths=[
                    GraphPathModel(
                        steps=[g.hop(h) for h in p.hops],
                        relationship_ids=[h.rel.id for h in p.hops],
                    )
                    for p in found
                ]
            )

        return await q(read)
