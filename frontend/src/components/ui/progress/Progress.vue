<script setup lang="ts">
import { ProgressIndicator, ProgressRoot } from "reka-ui";
import type { HTMLAttributes } from "vue";
import { computed } from "vue";
import { cn } from "@/lib/utils";

// modelValue null = progression indéterminée : aucune valeur annoncée aux lecteurs d'écran,
// la barre animée reste dessinée à mi-course.
const props = withDefaults(defineProps<{
  modelValue?: number | null;
  class?: HTMLAttributes["class"];
}>(), {
  modelValue: 0,
});

const safeValue = computed(() => (props.modelValue === null ? null : Math.max(0, Math.min(100, props.modelValue))));
const drawnValue = computed(() => safeValue.value ?? 46);
</script>

<template>
  <ProgressRoot
    :model-value="safeValue"
    :class="cn('relative h-1.5 w-full overflow-hidden rounded-full bg-white/8', props.class)"
  >
    <ProgressIndicator
      class="vue-progress-indicator h-full w-full flex-1 bg-gradient-to-r from-violet-500 to-emerald-500 transition-transform"
      :style="{ transform: `translateX(-${100 - drawnValue}%)` }"
    />
  </ProgressRoot>
</template>
