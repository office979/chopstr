/* Bildmarke: die Klinge, inline als SVG (Farbe über currentColor steuerbar) */
interface MarkProps {
  size?: number;
  className?: string;
  color?: string;
  title?: string;
}

export function Mark({ size = 24, className, color = "#020cf5", title = "chopstr" }: MarkProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 320 320"
      width={size}
      height={size}
      role="img"
      aria-label={title}
      className={className}
    >
      <title>{title}</title>
      <g transform="translate(160,20) scale(0.345) translate(-960.15,0)">
        <path
          fill={color}
          d="M992.42,0h-68.55c-14.41,0-26.09,11.68-26.09,26.09v33.11c0,14.41,11.68,26.09,26.09,26.09h20.71v709.66c0,7.39,5.99,13.38,13.38,13.38s13.38-5.99,13.38-13.38V85.28h21.08c14.41,0,26.09-11.68,26.09-26.09V26.09c0-14.41-11.68-26.09-26.09-26.09Z"
        />
      </g>
    </svg>
  );
}
