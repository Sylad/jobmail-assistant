<script setup lang="ts">
import { computed } from "vue";
import { Square } from "@lucide/vue";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import type { ProgressStat } from "./types";

const props = defineProps<{
  title: string;
  elapsedSeconds: number;
  active: boolean;
  cancelling: boolean;
  progressValue: number | null;
  stats: ProgressStat[];
}>();

const emit = defineEmits<{
  cancel: [];
}>();

// L4 : sans valeur connue, la barre est indéterminée pendant le travail et pleine une fois fini ;
// elle n'annonce plus un faux « 46 % » à la fin d'un scan.
const barValue = computed(() => props.progressValue ?? (props.active ? null : 100));
</script>

<template>
  <section class="scan-progress vue-progress-panel" aria-live="polite">
    <div class="scan-progress-head">
      <strong>{{ title }}</strong>
      <div class="vue-progress-actions">
        <span class="muted small">{{ elapsedSeconds }}s</span>
        <Button
          v-if="active"
          type="button"
          variant="ghost"
          size="sm"
          :disabled="cancelling"
          @click="emit('cancel')"
        >
          <Square :size="14" />
          {{ cancelling ? "Arrêt demandé" : "Arrêter" }}
        </Button>
      </div>
    </div>
    <Progress
      :model-value="barValue"
      :class="['vue-progress-bar', { 'vue-progress-bar-active': progressValue === null && active }]"
    />
    <div class="scan-progress-grid">
      <span v-for="stat in stats" :key="stat.label">
        {{ stat.label }} <strong>{{ stat.value }}</strong>
      </span>
    </div>
  </section>
</template>
