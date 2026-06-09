import { cva, type VariantProps } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/60 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "border border-white/10 bg-white/5 text-slate-200 hover:bg-white/8 hover:border-white/20 hover:text-white",
        destructive:
          "border border-red-400/30 bg-red-500/10 text-red-300 hover:bg-red-500/20 hover:border-red-400/50",
        ghost:
          "border border-white/8 bg-transparent text-slate-400 hover:bg-white/5 hover:border-white/15 hover:text-slate-200",
        secondary:
          "border border-violet-500/30 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20 hover:border-violet-500/50",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export type ButtonVariants = VariantProps<typeof buttonVariants>;
