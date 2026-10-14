import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "AI Civilization",
    short_name: "AI Civ",
    description: "A living city where your AI agents do real, supervised work.",
    start_url: "/",
    display: "standalone",
    orientation: "any",
    background_color: "#070B18",
    theme_color: "#070B18",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
