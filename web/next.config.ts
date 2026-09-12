import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  // `output: 'export'` was removed so the CopilotKit App Router API route
  // (`src/app/api/copilotkit/route.ts`) can run. Static export cannot host
  // server routes.
  // `<Image>` optimisation requires a Node server; we're serving from disk.
  images: { unoptimized: true },
  experimental: {
    optimizePackageImports: ["@chakra-ui/react"],
  },
}

export default nextConfig
