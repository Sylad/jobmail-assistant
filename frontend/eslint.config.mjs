// Analyse statique du frontend Vue/TS (L24, D-31 du registre parent ; `analyse:` de cadence.yaml).
// Lancé par `cadence analyse` dans frontend/ (`npx eslint -f json .`) ; l'existant est figé dans
// .cadence/analyse/eslint.json, seules les violations nouvelles échouent. Ce fichier est dans `configs:` :
// changer un seuil ou une exclusion = lot `config: true` du plan.
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";
import sonarjs from "eslint-plugin-sonarjs";
import vueParser from "vue-eslint-parser";

// Seuils de taille de cadence, en avertissement : `cadence analyse` compte les constats, pas le code de sortie.
const tailles = {
  "max-lines": ["warn", { max: 400 }],
  "max-lines-per-function": ["warn", { max: 80 }],
  "max-depth": ["warn", { max: 4 }],
  "max-params": ["warn", { max: 5 }],
  complexity: ["warn", { max: 15 }],
  "sonarjs/cognitive-complexity": ["warn", 15],
};

// Vue : « essential » (erreurs de correction) ; pas les règles de mise en forme de « recommended »,
// qui gèleraient ~180 constats de présentation sans rapport avec la qualité du code.
export default tseslint.config(
  { ignores: ["node_modules/", "dist/", "eslint.config.mjs", "vite.config.js"] },
  ...tseslint.configs.recommendedTypeChecked,
  ...pluginVue.configs["flat/essential"],
  {
    files: ["**/*.ts", "**/*.vue"],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: [".vue"],
        sourceType: "module",
      },
    },
    plugins: { sonarjs },
    rules: tailles,
  },
);
