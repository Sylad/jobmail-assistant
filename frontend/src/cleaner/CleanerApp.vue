<script setup lang="ts">
import { onMounted, ref } from "vue";
import ProgressPanel from "./ProgressPanel.vue";
import { useCandidateSelection } from "./useCandidateSelection";
import { useMoveJobs } from "./useMoveJobs";
import { useRegexRules } from "./useRegexRules";
import { useScanJobs } from "./useScanJobs";

const { initCandidateSelection } = useCandidateSelection();
const { initRegexRules } = useRegexRules();
const scanJobs = useScanJobs();
const moveJobs = useMoveJobs();
const hasMoveProgressTarget = ref(false);

onMounted(() => {
  initCandidateSelection();
  initRegexRules();
  scanJobs.initScanForms();
  moveJobs.initMoveForm();
  hasMoveProgressTarget.value = Boolean(document.querySelector("#cleaner-move-progress-root"));
});
</script>

<template>
  <ProgressPanel
    v-if="scanJobs.panel.visible"
    :title="scanJobs.panel.title"
    :elapsed-seconds="scanJobs.panel.elapsedSeconds"
    :active="scanJobs.panel.active"
    :cancelling="scanJobs.panel.cancelling"
    :progress-value="scanJobs.panel.progressValue"
    :stats="scanJobs.panel.stats"
    @cancel="scanJobs.cancelScan"
  />
  <Teleport v-if="hasMoveProgressTarget" to="#cleaner-move-progress-root">
    <ProgressPanel
      v-if="moveJobs.panel.visible"
      :title="moveJobs.panel.title"
      :elapsed-seconds="moveJobs.panel.elapsedSeconds"
      :active="moveJobs.panel.active"
      :cancelling="moveJobs.panel.cancelling"
      :progress-value="moveJobs.panel.progressValue"
      :stats="moveJobs.panel.stats"
      @cancel="moveJobs.cancelMove"
    />
  </Teleport>
</template>
