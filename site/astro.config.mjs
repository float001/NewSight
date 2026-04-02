import { defineConfig } from "astro/config";

const ghRepo = process.env.GITHUB_REPOSITORY || "";
const [ghOwner, ghName] = ghRepo.includes("/") ? ghRepo.split("/") : ["", ""];
const isGhPages = Boolean(process.env.GITHUB_ACTIONS) && Boolean(ghOwner) && Boolean(ghName);
const siteUrl = isGhPages ? `https://${ghOwner}.github.io/${ghName}/` : "https://example.com/";
const basePath = isGhPages ? `/${ghName}/` : "/";

export default defineConfig({
  site: siteUrl,
  base: basePath,
  output: "static",
  outDir: "./dist",
  markdown: {
    shikiConfig: { theme: "github-dark" }
  }
});

