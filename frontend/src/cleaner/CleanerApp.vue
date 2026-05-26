<script setup lang="ts">
import { onMounted } from "vue";
import { useCandidateSelection } from "./useCandidateSelection";
import { useMoveJobs } from "./useMoveJobs";
import { useRegexRules } from "./useRegexRules";
import { useScanJobs } from "./useScanJobs";

const { initCandidateSelection } = useCandidateSelection();
const { initRegexRules } = useRegexRules();
const { initScanForms } = useScanJobs();
const { initMoveForm } = useMoveJobs();

onMounted(() => {
  initCandidateSelection();
  initRegexRules();
  initScanForms();
  initMoveForm();
});
</script>

<template></template>
