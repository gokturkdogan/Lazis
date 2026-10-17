import { createPinia } from "pinia";
import { createApp } from "vue";
import App from "./App.vue";
import { createAppI18n } from "./i18n";
import { tauriPlatform } from "./platform/tauri";
import { useConnectionStore } from "./stores/connection";
import "./styles/theme.css";

const app = createApp(App);
app.use(createPinia());
app.use(createAppI18n());
app.mount("#app");

void useConnectionStore().start({ platform: tauriPlatform });
