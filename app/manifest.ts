import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "GatePath 2027",
    short_name: "GatePath",
    description:
      "A focused GATE 2027 CSE roadmap with notes, practice, analytics and full-length mocks.",
    start_url: "/",
    display: "standalone",
    background_color: "#F5F7FB",
    theme_color: "#4056D6",
    icons: [
      {
        src: "/icon.svg",
        sizes: "any",
        type: "image/svg+xml",
      },
    ],
  };
}
