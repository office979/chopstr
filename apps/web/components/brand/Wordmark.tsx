/* Wortmarke aus public/brand (Pfade, keine Schriftabhängigkeit). Seitenverhältnis 1530:834. */
interface WordmarkProps {
  variant?: "light" | "on-dark" | "black";
  width?: number;
  className?: string;
}

const FILES: Record<NonNullable<WordmarkProps["variant"]>, string> = {
  light: "/brand/chopstr-wordmark.svg",
  "on-dark": "/brand/chopstr-wordmark-on-dark.svg",
  black: "/brand/chopstr-wordmark-black.svg",
};

export function Wordmark({ variant = "light", width = 160, className }: WordmarkProps) {
  const height = Math.round((width * 834) / 1530);
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={FILES[variant]}
      alt="chopstr"
      width={width}
      height={height}
      className={className}
      draggable={false}
    />
  );
}
