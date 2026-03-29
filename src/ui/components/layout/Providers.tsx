"use client";

import { ReactNode } from "react";
import { MeshProvider } from "@/lib/mesh-context";

export function Providers({ children }: { children: ReactNode }) {
  return <MeshProvider>{children}</MeshProvider>;
}
