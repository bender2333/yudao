# Scenario 1 Interface Agreement

This agreement defines the startup and communication conventions for Scenario 1 (WebGen-Bench 000080 advanced to-do list web application).

## 1. Application Startup
- The delivery is a Node.js web application located in the root of the delivery directory.
- If `package.json` is provided:
  - Any required dependencies are installed via `npm install`.
  - The application is started via `npm run dev` if a `dev` script is defined, or `npm run start` / `npm start` if a `start` script is defined.
- If standalone scripts `server.js` or `index.js` are provided without a `package.json` start script, the application can be started directly via `node server.js` or `node index.js`.
- The startup port is passed via the environment variable `PORT` (e.g. `process.env.PORT`). The application server MUST bind and listen on `0.0.0.0` or `127.0.0.1` on the port specified by `PORT`.

## 2. Interaction and Interface
- The web interface is accessed at `http://localhost:$PORT/` (or `http://127.0.0.1:$PORT/`).
- Page elements do not require specific IDs, class names, or data attributes. The UI agent operates the interface based on visible elements, labels, and text.
- Styling requirements:
  - All pages must have a `lavender` background color.
  - Components (such as buttons, headers, cards, navigation items) must be styled with the color `indigo`.
