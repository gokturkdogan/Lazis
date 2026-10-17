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
// Start before mounting: `start()` registers the platform synchronously, and App's onMounted
// needs it (menu-bar navigation, --show, preferences, the first menu-bar status).
void useConnectionStore().start({ platform: tauriPlatform });
app.mount("#app");
