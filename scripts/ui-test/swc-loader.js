const swc = require("../../next-ui/node_modules/next/dist/build/swc");

module.exports = function swcLoader(source) {
  const done = this.async();
  swc.transform(source, {
    filename: this.resourcePath,
    sourceMaps: true,
    jsc: {
      parser: { syntax: "ecmascript", jsx: true },
      transform: { react: { runtime: "automatic" } },
    },
    module: { type: "es6" },
  }).then((output) => done(null, output.code, output.map), done);
};