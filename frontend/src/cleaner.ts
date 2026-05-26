import { createApp } from "vue";
import CleanerApp from "./cleaner/CleanerApp.vue";
import "./styles/tailwind.css";

const mount = document.querySelector<HTMLElement>("#cleaner-vue-root");

if (mount) {
  const initial = mount.dataset.initial ? JSON.parse(mount.dataset.initial) : {};
  createApp(CleanerApp, { initial }).mount(mount);
}
