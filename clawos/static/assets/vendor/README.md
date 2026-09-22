# Browser dependency

`markdown-it-14.1.0.min.js` is the unchanged browser bundle from npm package
`markdown-it@14.1.0` (`package/dist/markdown-it.min.js`). Its MIT license is
retained in `markdown-it-LICENSE.txt`. The bundle includes its dependencies.

The console loads this local asset; no runtime CDN or npm installation is needed.
The application integration is in `../chat-content.js`. Update the versioned
filename, license and rendering regression tests together when upgrading.
