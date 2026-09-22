"use client";

import { Button } from "@/components/ui/Button";

export function PrintButton() {
  return (
    <Button variant="ghost" size="sm" onClick={() => window.print()}>
      Drucken
    </Button>
  );
}
