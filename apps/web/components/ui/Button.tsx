import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "./cn";

type Variant = "primary" | "ghost" | "danger";
type Size = "sm" | "md";

const base =
  "transition-soft inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-pill font-medium disabled:cursor-not-allowed disabled:opacity-50";

const variants: Record<Variant, string> = {
  /* Weiß = Aktion */
  primary: "bg-text text-black hover:bg-white hover:shadow-[0_0_32px_rgba(244,245,254,0.25)]",
  /* Ghost: 1-px-Rand */
  ghost: "border border-line-strong bg-transparent text-text hover:border-white/40 hover:bg-white/5",
  /* Danger: nur Text */
  danger: "bg-transparent text-danger hover:bg-danger/10",
};

const sizes: Record<Size, string> = {
  sm: "h-9 px-4 text-sm",
  md: "h-11 px-6 text-[15px]",
};

interface ButtonBaseProps {
  variant?: Variant;
  size?: Size;
  className?: string;
  children: ReactNode;
}

type ButtonProps = ButtonBaseProps & Omit<ComponentProps<"button">, "className" | "children">;

export function Button({ variant = "primary", size = "md", className, children, type = "button", ...rest }: ButtonProps) {
  return (
    <button type={type} className={cn(base, variants[variant], sizes[size], className)} {...rest}>
      {children}
    </button>
  );
}

type ButtonLinkProps = ButtonBaseProps & { href: string; prefetch?: boolean };

export function ButtonLink({ variant = "primary", size = "md", className, children, href, prefetch }: ButtonLinkProps) {
  return (
    <Link href={href} prefetch={prefetch} className={cn(base, variants[variant], sizes[size], className)}>
      {children}
    </Link>
  );
}
