const path = require("path");
const nextWebpack = require("../../next-ui/node_modules/next/dist/compiled/webpack/webpack");

async function main() {
  await nextWebpack.init();
  const webpack = nextWebpack.webpack;
  const root = path.resolve(__dirname, "../..");
  const compiler = webpack({
    mode: "development",
    devtool: false,
    target: "web",
    entry: path.join(__dirname, "entry.jsx"),
    output: {
      path: "/tmp",
      filename: "datalake-ui-bundle.js",
    },
    resolve: {
      extensions: [".js", ".jsx"],
      alias: {
        "@clerk/react$": path.join(__dirname, "clerk-stub.jsx"),
        react: path.join(root, "next-ui/node_modules/react"),
        "react-dom": path.join(root, "next-ui/node_modules/react-dom"),
      },
    },
    module: {
      rules: [{
        test: /\.[jt]sx?$/,
        exclude: /node_modules/,
        use: path.join(__dirname, "swc-loader.js"),
      }],
    },
  });

  await new Promise((resolve, reject) => {
    compiler.run((error, stats) => {
      compiler.close(() => {});
      if (error) return reject(error);
      if (stats.hasErrors()) {
        return reject(new Error(stats.toString({ all: false, errors: true })));
      }
      resolve();
    });
  });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});