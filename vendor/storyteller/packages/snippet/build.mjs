import { build } from "esbuild";
const common = { entryPoints: ["src/index.ts"], bundle: true, minify: true, sourcemap: true, target: ["es2019"], legalComments: "none" };
await build({ ...common, format: "iife", globalName: "storytellerModule", outfile: "dist/storyteller.js" });
await build({ ...common, format: "esm", outfile: "dist/storyteller.esm.js" });
console.log("built dist/storyteller.js and dist/storyteller.esm.js");
