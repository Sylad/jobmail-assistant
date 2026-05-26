import { cva, type VariantProps } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "border border-slate-700 bg-slate-800 text-slate-50 hover:border-sky-400 hover:text-sky-200",
        destructive: "border border-red-400/50 bg-red-500/10 text-red-200 hover:bg-red-500/20",
        ghost: "border border-slate-700/70 bg-transparent text-slate-200 hover:border-sky-400 hover:text-sky-200",
        secondary: "border border-slate-700 bg-slate-900 text-slate-200 hover:bg-slate-800",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3",
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
