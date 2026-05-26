<script setup lang="ts">
import { ProgressIndicator, ProgressRoot } from "reka-ui";
import { computed } from "vue";
import { cn } from "@/lib/utils";

const props = withDefaults(defineProps<{
  modelValue?: number;
  class?: string;
}>(), {
  modelValue: 0,
});

const safeValue = computed(() => Math.max(0, Math.min(100, props.modelValue)));
</script>

<template>
  <ProgressRoot
    :model-value="safeValue"
    :class="cn('relative h-2 w-full overflow-hidden rounded-full bg-slate-900', props.class)"
  >
    <ProgressIndicator
      class="h-full w-full flex-1 bg-gradient-to-r from-sky-400 to-emerald-400 transition-transform"
      :style="{ transform: `translateX(-${100 - safeValue}%)` }"
    />
  </ProgressRoot>
</template>
