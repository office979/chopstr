import type { ComponentProps, ElementType, ReactNode } from "react";
import { cn } from "./cn";

interface GlassCardProps {
  as?: ElementType;
  selected?: boolean;
  strong?: boolean;
  padding?: "none" | "sm" | "md" | "lg";
  className?: string;
  children: ReactNode;
}

const paddings = {
  none: "",
  sm: "p-4",
  md: "p-6",
  lg: "p-6 sm:p-8",
};

/* Glas-Karte: Radius 30 px, 1-px-Lichtrand, helle Innenkante oben, Auswahl = --ai-glow */
export function GlassCard({
  as: Tag = "div",
  selected = false,
  strong = false,
  padding = "md",
  className,
  children,
  ...rest
}: GlassCardProps & Omit<ComponentProps<"div">, "className" | "children">) {
  return (
    <Tag
      className={cn(
        "glass transition-soft relative rounded-card",
        strong && "glass-strong",
        selected && "glass-selected",
        paddings[padding],
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}
