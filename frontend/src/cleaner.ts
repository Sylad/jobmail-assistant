import { createApp } from "vue";
import CleanerApp from "./cleaner/CleanerApp.vue";
import "./styles/tailwind.css";

const mount = document.querySelector("#cleaner-vue-root");

if (mount) {
  createApp(CleanerApp).mount(mount);
}
