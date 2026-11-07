//! Voice (Phase 13, first version): speech-to-text with whisper.cpp, text-to-speech with the
//! macOS system voice. Everything stays on this machine.
//!
//! * **STT.** `whisper-server` (whisper.cpp, Metal) runs only while voice is used: started on
//!   the first transcription, stopped after [`IDLE`] without use, when the user ends a voice
//!   session, or when the app quits. It runs under `sandbox/stt.sb` (no outbound network at all,
//!   loopback listening only) behind a `/bin/sh` lifeline: if the shell dies, the pipe closes and
//!   the server is killed. Audio comes from the UI as a 16 kHz mono WAV in memory, is sent to
//!   the server over loopback and is never written to disk by LAZIS.
//! * **TTS.** `/usr/bin/say` with the Turkish system voice, text on stdin (not in argv), one
//!   sentence at a time; [`Voice::stop_speaking`] stops it at once.
//!
//! The microphone itself is opened by the UI only while the user holds push-to-talk or keeps a
//! hands-free session open; this module never touches it.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;

use crate::backend::SANDBOX_EXEC;
use crate::errors::ShellError;

pub const STT_PROFILE: &str = include_str!("../sandbox/stt.sb");
/// whisper large-v3-turbo, 5-bit quantized (about 574 MB): installed by `make voice-model`.
pub const MODEL_FILE: &str = "ggml-large-v3-turbo-q5_0.bin";
pub const DEFAULT_SERVER: &str = "/opt/homebrew/bin/whisper-server";
const SAY: &str = "/usr/bin/say";
pub const TTS_VOICE: &str = "Yelda";
/// At most 60 s of 16 kHz mono 16-bit audio per utterance (plus the WAV header).
pub const MAX_AUDIO_BYTES: usize = 16_000 * 2 * 60 + 44;
pub const MAX_SPEAK_CHARS: usize = 2_000;
pub const IDLE: Duration = Duration::from_secs(120);
const READY_TIMEOUT: Duration = Duration::from_secs(60);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(60);
const MAX_RESPONSE: usize = 256 * 1024;

#[derive(Debug, Clone)]
pub struct VoiceConfig {
    pub server: PathBuf,
    pub model: PathBuf,
    pub threads: u32,
    pub idle: Duration,
}

impl VoiceConfig {
    /// Models are shared by profiles (they are not user data):
    /// `~/Library/Application Support/LAZIS/models/whisper/`. `LAZIS_STT_MODEL` and
    /// `LAZIS_WHISPER_SERVER` override the paths.
    pub fn from_env(home: &Path) -> Self {
        let model = std::env::var_os("LAZIS_STT_MODEL").map(PathBuf::from).unwrap_or_else(|| {
            home.join("Library/Application Support/LAZIS/models/whisper").join(MODEL_FILE)
        });
        let server = std::env::var_os("LAZIS_WHISPER_SERVER")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from(DEFAULT_SERVER));
        Self { server, model, threads: 4, idle: IDLE }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct VoiceStatus {
    pub stt_available: bool,
    /// Why not: `stt_server_missing` (whisper.cpp not installed) or `stt_model_missing`.
    pub stt_reason: Option<String>,
    pub stt_running: bool,
    pub tts_available: bool,
    pub tts_voice: Option<String>,
}

struct SttServer {
    child: Child,
    lifeline: Option<ChildStdin>,
    addr: SocketAddr,
}

impl Drop for SttServer {
    fn drop(&mut self) {
        drop(self.lifeline.take()); // the wrapper kills the server when this closes
        let until = Instant::now() + Duration::from_secs(2);
        while Instant::now() < until {
            if let Ok(Some(_)) = self.child.try_wait() {
                return;
            }
            thread::sleep(Duration::from_millis(25));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct Voice {
    cfg: VoiceConfig,
    stt: Mutex<Option<SttServer>>,
    last_used: Mutex<Instant>,
    speaking: Mutex<Option<Child>>,
    tts_voice: OnceLock<Option<String>>,
}

impl Voice {
    /// Also starts a small reaper thread that stops the STT server after `cfg.idle`.
    pub fn new(cfg: VoiceConfig) -> Arc<Self> {
        let voice = Arc::new(Self {
            cfg,
            stt: Mutex::new(None),
            last_used: Mutex::new(Instant::now()),
            speaking: Mutex::new(None),
            tts_voice: OnceLock::new(),
        });
        let weak: Weak<Self> = Arc::downgrade(&voice);
        let _ = thread::Builder::new().name("voice-idle".into()).spawn(move || {
            loop {
                thread::sleep(Duration::from_secs(5));
                let Some(voice) = weak.upgrade() else { return };
                voice.stop_if_idle();
            }
        });
        voice
    }

    fn stop_if_idle(&self) {
        let idle = self.last_used.lock().map(|t| t.elapsed() >= self.cfg.idle).unwrap_or(true);
        if idle {
            let stopped = self.stt.lock().ok().and_then(|mut s| s.take()).is_some();
            if stopped {
                log::info!("voice.stt_stopped reason=idle");
            }
        }
    }

    pub fn status(&self) -> VoiceStatus {
        let reason = if !self.cfg.server.exists() || !Path::new(SANDBOX_EXEC).exists() {
            Some("stt_server_missing".to_owned())
        } else if !self.cfg.model.is_file() {
            Some("stt_model_missing".to_owned())
        } else {
            None
        };
        let voice = self.tts_voice().clone();
        VoiceStatus {
            stt_available: reason.is_none(),
            stt_reason: reason,
            stt_running: self.stt.lock().map(|s| s.is_some()).unwrap_or(false),
            tts_available: voice.is_some(),
            tts_voice: voice,
        }
    }

    fn tts_voice(&self) -> &Option<String> {
        self.tts_voice.get_or_init(|| {
            let out = Command::new(SAY).args(["-v", "?"]).env_clear().output().ok()?;
            let list = String::from_utf8_lossy(&out.stdout);
            list.lines()
                .any(|l| l.starts_with(TTS_VOICE) && l.contains("tr_TR"))
                .then(|| TTS_VOICE.to_owned())
        })
    }

    /// Stop the STT server now (the user ended the voice session).
    pub fn release(&self) {
        if self.stt.lock().ok().and_then(|mut s| s.take()).is_some() {
            log::info!("voice.stt_stopped reason=released");
        }
    }

    pub fn transcribe(&self, wav: &[u8]) -> Result<String, ShellError> {
        check_wav(wav)?;
        if let Some(reason) = self.status().stt_reason {
            return Err(ShellError::new(&reason));
        }
        if let Ok(mut t) = self.last_used.lock() {
            *t = Instant::now();
        }
        let started = Instant::now();
        let mut guard = self.stt.lock().map_err(|_| ShellError::new("stt_failed"))?;
        if guard.as_mut().is_some_and(|s| !matches!(s.child.try_wait(), Ok(None))) {
            *guard = None; // it exited: start a new one
        }
        if guard.is_none() {
            *guard = Some(start_server(&self.cfg)?);
        }
        let addr = guard.as_ref().map(|s| s.addr).ok_or_else(|| ShellError::new("stt_failed"))?;
        let result = post_inference(addr, wav);
        if result.is_err() {
            *guard = None; // a broken server is not reused
        }
        drop(guard);
        if let Ok(mut t) = self.last_used.lock() {
            *t = Instant::now();
        }
        let text = result?;
        log::info!("voice.transcribed ms={} chars={}", started.elapsed().as_millis(), text.chars().count());
        Ok(text)
    }

    /// Speak one piece of text; returns when it is done or stopped.
    pub fn speak(&self, text: &str) -> Result<(), ShellError> {
        let Some(voice) = self.tts_voice().clone() else { return Err(ShellError::new("tts_unavailable")) };
        let text: String = text.chars().take(MAX_SPEAK_CHARS).collect();
        if text.trim().is_empty() {
            return Ok(());
        }
        let mut child = Command::new(SAY)
            .args(["-v", &voice, "-f", "-"])
            .env_clear()
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| ShellError::new("tts_failed"))?;
        if let Some(mut stdin) = child.stdin.take() {
            let _ = stdin.write_all(text.as_bytes());
        }
        let pid = child.id();
        self.stop_speaking(); // one voice at a time
        *self.speaking.lock().map_err(|_| ShellError::new("tts_failed"))? = Some(child);
        loop {
            {
                let mut slot = self.speaking.lock().map_err(|_| ShellError::new("tts_failed"))?;
                match slot.as_mut() {
                    Some(c) if c.id() == pid => {
                        if let Ok(Some(_)) = c.try_wait() {
                            *slot = None;
                            return Ok(());
                        }
                    }
                    _ => return Ok(()), // stopped (or replaced) by the user
                }
            }
            thread::sleep(Duration::from_millis(40));
        }
    }

    pub fn stop_speaking(&self) {
        let child = self.speaking.lock().ok().and_then(|mut slot| slot.take());
        if let Some(mut child) = child {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for Voice {
    fn drop(&mut self) {
        self.stop_speaking();
        self.release();
    }
}

/// A 16 kHz mono 16-bit PCM WAV, within the size limit.
pub fn check_wav(wav: &[u8]) -> Result<(), ShellError> {
    let ok = wav.len() > 44
        && wav.len() <= MAX_AUDIO_BYTES
        && &wav[0..4] == b"RIFF"
        && &wav[8..12] == b"WAVE"
        && &wav[12..16] == b"fmt "
        && u16::from_le_bytes([wav[20], wav[21]]) == 1 // PCM
        && u16::from_le_bytes([wav[22], wav[23]]) == 1 // mono
        && u32::from_le_bytes([wav[24], wav[25], wav[26], wav[27]]) == 16_000
        && u16::from_le_bytes([wav[34], wav[35]]) == 16;
    if ok { Ok(()) } else { Err(ShellError::new("audio_invalid")) }
}

fn free_port() -> Result<u16, ShellError> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|_| ShellError::new("stt_failed"))?;
    Ok(listener.local_addr().map_err(|_| ShellError::new("stt_failed"))?.port())
}

fn start_server(cfg: &VoiceConfig) -> Result<SttServer, ShellError> {
    let port = free_port()?;
    let started = Instant::now();
    // /bin/sh holds the lifeline: when the shell's end of stdin closes, the server is killed.
    let mut child = Command::new(SANDBOX_EXEC)
        .arg("-p")
        .arg(STT_PROFILE)
        .args([
            "/bin/sh",
            "-c",
            "\"$@\" </dev/null >/dev/null 2>&1 & p=$!; read _; kill $p 2>/dev/null; wait $p",
            "lazis-stt",
        ])
        .arg(&cfg.server)
        .arg("-m")
        .arg(&cfg.model)
        .args([
            "-l",
            "tr",
            "-t",
            &cfg.threads.to_string(),
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .current_dir("/")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| {
            log::warn!("voice.stt_spawn_failed kind={:?}", e.kind());
            ShellError::new("stt_failed")
        })?;
    let lifeline = child.stdin.take();
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut server = SttServer { child, lifeline, addr };
    // The server listens once the model is loaded.
    while started.elapsed() < READY_TIMEOUT {
        if let Ok(Some(_)) = server.child.try_wait() {
            log::warn!("voice.stt_exited_before_ready");
            return Err(ShellError::new("stt_failed"));
        }
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            log::info!("voice.stt_ready ms={}", started.elapsed().as_millis());
            return Ok(server);
        }
        thread::sleep(Duration::from_millis(100));
    }
    log::warn!("voice.stt_start_timeout");
    drop(server.lifeline.take());
    Err(ShellError::new("stt_failed"))
}

const BOUNDARY: &str = "lazis-voice-7f3a9c";

/// The multipart body whisper-server's `/inference` expects (no file on disk).
pub fn multipart(wav: &[u8]) -> Vec<u8> {
    let mut body = Vec::with_capacity(wav.len() + 512);
    for (name, value) in [("response_format", "json"), ("language", "tr"), ("temperature", "0.0")] {
        body.extend_from_slice(
            format!("--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n")
                .as_bytes(),
        );
    }
    body.extend_from_slice(
        format!(
            "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n\
             Content-Type: audio/wav\r\n\r\n"
        )
        .as_bytes(),
    );
    body.extend_from_slice(wav);
    body.extend_from_slice(format!("\r\n--{BOUNDARY}--\r\n").as_bytes());
    body
}

/// POST the audio and return the recognized text (trimmed).
pub fn post_inference(addr: SocketAddr, wav: &[u8]) -> Result<String, ShellError> {
    let fail = |what: &str| {
        log::warn!("voice.stt_request_failed step={what}");
        ShellError::new("stt_failed")
    };
    let body = multipart(wav);
    let mut stream =
        TcpStream::connect_timeout(&addr, Duration::from_secs(5)).map_err(|_| fail("connect"))?;
    stream.set_read_timeout(Some(REQUEST_TIMEOUT)).map_err(|_| fail("timeout"))?;
    stream.set_write_timeout(Some(REQUEST_TIMEOUT)).map_err(|_| fail("timeout"))?;
    let head = format!(
        "POST /inference HTTP/1.1\r\nHost: {addr}\r\nContent-Type: multipart/form-data; boundary={BOUNDARY}\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream.write_all(head.as_bytes()).and_then(|()| stream.write_all(&body)).map_err(|_| fail("write"))?;
    let mut response = Vec::new();
    stream.take(MAX_RESPONSE as u64 + 1).read_to_end(&mut response).map_err(|_| fail("read"))?;
    if response.len() > MAX_RESPONSE {
        return Err(fail("too_large"));
    }
    let split = response.windows(4).position(|w| w == b"\r\n\r\n").ok_or_else(|| fail("head"))?;
    let status_line = String::from_utf8_lossy(&response[..split]);
    if !status_line.lines().next().is_some_and(|l| l.split_whitespace().nth(1) == Some("200")) {
        return Err(fail("status"));
    }
    let head_text = status_line.to_ascii_lowercase();
    let raw = &response[split + 4..];
    let payload = if head_text.contains("transfer-encoding: chunked") {
        dechunk(raw).ok_or_else(|| fail("chunked"))?
    } else {
        raw.to_vec()
    };
    let json: serde_json::Value = serde_json::from_slice(&payload).map_err(|_| fail("json"))?;
    let text = json.get("text").and_then(|t| t.as_str()).ok_or_else(|| fail("json"))?;
    Ok(joined(text))
}

/// whisper-server joins its segments with newlines, sometimes inside a word ("ha\nva");
/// a segment that starts a new word carries its own leading space.
pub fn joined(text: &str) -> String {
    text.replace(['\r', '\n'], "").split_whitespace().collect::<Vec<_>>().join(" ")
}

fn dechunk(mut raw: &[u8]) -> Option<Vec<u8>> {
    let mut out = Vec::new();
    loop {
        let line_end = raw.windows(2).position(|w| w == b"\r\n")?;
        let size_text = std::str::from_utf8(&raw[..line_end]).ok()?;
        let size = usize::from_str_radix(size_text.split(';').next()?.trim(), 16).ok()?;
        raw = &raw[line_end + 2..];
        if size == 0 {
            return Some(out);
        }
        out.extend_from_slice(raw.get(..size)?);
        raw = raw.get(size + 2..)?;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    pub(crate) fn wav(samples: usize) -> Vec<u8> {
        let data = samples * 2;
        let mut w = Vec::new();
        w.extend_from_slice(b"RIFF");
        w.extend_from_slice(&((36 + data) as u32).to_le_bytes());
        w.extend_from_slice(b"WAVEfmt ");
        w.extend_from_slice(&16u32.to_le_bytes());
        w.extend_from_slice(&1u16.to_le_bytes());
        w.extend_from_slice(&1u16.to_le_bytes());
        w.extend_from_slice(&16_000u32.to_le_bytes());
        w.extend_from_slice(&32_000u32.to_le_bytes());
        w.extend_from_slice(&2u16.to_le_bytes());
        w.extend_from_slice(&16u16.to_le_bytes());
        w.extend_from_slice(b"data");
        w.extend_from_slice(&(data as u32).to_le_bytes());
        w.resize(44 + data, 0);
        w
    }

    #[test]
    fn only_16khz_mono_pcm_within_the_limit() {
        assert!(check_wav(&wav(16_000)).is_ok());
        assert!(check_wav(&wav(0)).is_err());
        assert!(check_wav(b"not audio at all, not even close to a wav header....").is_err());
        let mut stereo = wav(100);
        stereo[22] = 2;
        assert!(check_wav(&stereo).is_err());
        let mut rate = wav(100);
        rate[24..28].copy_from_slice(&44_100u32.to_le_bytes());
        assert!(check_wav(&rate).is_err());
        assert_eq!(check_wav(&wav(16_000 * 61)).unwrap_err().code, "audio_invalid");
    }

    #[test]
    fn multipart_carries_turkish_and_the_audio() {
        let audio = wav(10);
        let body = multipart(&audio);
        let text = String::from_utf8_lossy(&body);
        assert!(text.contains("name=\"language\"\r\n\r\ntr\r\n"));
        assert!(text.contains("name=\"response_format\"\r\n\r\njson\r\n"));
        assert!(body.windows(audio.len()).any(|w| w == audio.as_slice()));
        assert!(text.ends_with(&format!("--{BOUNDARY}--\r\n")));
    }

    fn fake_server(reply: &'static [u8]) -> (SocketAddr, thread::JoinHandle<Vec<u8>>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let handle = thread::spawn(move || {
            let (mut conn, _) = listener.accept().unwrap();
            conn.set_read_timeout(Some(Duration::from_millis(500))).unwrap();
            let mut got = Vec::new();
            let mut buf = [0u8; 65536];
            while let Ok(n) = conn.read(&mut buf) {
                if n == 0 {
                    break;
                }
                got.extend_from_slice(&buf[..n]);
                if got.ends_with(format!("--{BOUNDARY}--\r\n").as_bytes()) {
                    break;
                }
            }
            conn.write_all(reply).unwrap();
            got
        });
        (addr, handle)
    }

    #[test]
    fn a_transcription_round_trip_over_loopback() {
        let (addr, server) = fake_server(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"text\":\"  Merhaba LAZIS, bug\xc3\xbcn hava nas\xc4\xb1l?\\n\"}",
        );
        let text = post_inference(addr, &wav(1600)).unwrap();
        assert_eq!(text, "Merhaba LAZIS, bugün hava nasıl?");
        let request = server.join().unwrap();
        assert!(request.starts_with(b"POST /inference HTTP/1.1\r\n"));
    }

    #[test]
    fn segments_are_joined_without_breaking_words() {
        // Real whisper-server output for a Turkish sentence (2026-11-07 check).
        let raw = " Merhaba Lazız, yarın sabah saat 9'da toplantım var. Bana ha\nva durumunu söyler misin?\n";
        assert_eq!(
            joined(raw),
            "Merhaba Lazız, yarın sabah saat 9'da toplantım var. Bana hava durumunu söyler misin?"
        );
        assert_eq!(joined(" Birinci cümle.\n İkinci cümle.\n"), "Birinci cümle. İkinci cümle.");
    }

    #[test]
    fn chunked_replies_and_errors() {
        let (addr, _s) = fake_server(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nC\r\n{\"text\":\"Ev\"\r\n1\r\n}\r\n0\r\n\r\n",
        );
        assert_eq!(post_inference(addr, &wav(10)).unwrap(), "Ev");
        let (addr, _s) = fake_server(b"HTTP/1.1 500 Internal Server Error\r\n\r\n{}");
        assert_eq!(post_inference(addr, &wav(10)).unwrap_err().code, "stt_failed");
        let (addr, _s) = fake_server(b"HTTP/1.1 200 OK\r\n\r\nnot json");
        assert_eq!(post_inference(addr, &wav(10)).unwrap_err().code, "stt_failed");
    }

    #[test]
    fn status_names_what_is_missing_and_nothing_starts() {
        let dir = tempfile::tempdir().unwrap();
        let voice = Voice::new(VoiceConfig {
            server: dir.path().join("no-whisper-server"),
            model: dir.path().join(MODEL_FILE),
            threads: 1,
            idle: IDLE,
        });
        let status = voice.status();
        assert!(!status.stt_available && !status.stt_running);
        assert_eq!(status.stt_reason.as_deref(), Some("stt_server_missing"));
        assert_eq!(voice.transcribe(&wav(1600)).unwrap_err().code, "stt_server_missing");
        assert!(!voice.status().stt_running);

        let fake_server = dir.path().join("whisper-server");
        std::fs::write(&fake_server, b"").unwrap();
        let voice = Voice::new(VoiceConfig {
            server: fake_server,
            model: dir.path().join(MODEL_FILE),
            threads: 1,
            idle: IDLE,
        });
        assert_eq!(voice.status().stt_reason.as_deref(), Some("stt_model_missing"));
        assert_eq!(voice.transcribe(&wav(1600)).unwrap_err().code, "stt_model_missing");
        assert_eq!(voice.transcribe(b"RIFF").unwrap_err().code, "audio_invalid");
    }
}
