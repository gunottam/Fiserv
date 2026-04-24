---
name: spline-react-integration
description: How to integrate Spline 3D scenes into React (Vite) applications using @splinetool/react-spline
---

# Spline 3D Integration for React

This skill covers how to integrate interactive 3D Spline scenes into React apps built with Vite.

## Prerequisites

Install the required packages:

```bash
npm install @splinetool/react-spline @splinetool/runtime
```

Both packages are required:

- `@splinetool/react-spline` — The React component wrapper
- `@splinetool/runtime` — The underlying Spline rendering engine

## Getting a Scene URL

1. Open your scene in the [Spline Editor](https://app.spline.design)
2. Click the **Export** button (top right)
3. Select **Code** → **React**
4. Copy the generated URL (format: `https://prod.spline.design/<ID>/scene.splinecode`)

> **CORS Fix:** If you get CORS errors, download the `.splinecode` file from the export panel and host it locally in your `public/` folder. Then reference it as `/scene.splinecode`.

---

## Basic Usage

```jsx
import Spline from "@splinetool/react-spline";

export default function App() {
  return (
    <Spline scene="https://prod.spline.design/YOUR_SCENE_ID/scene.splinecode" />
  );
}
```

## Lazy Loading (Recommended for Performance)

Use `React.lazy()` to defer loading the heavy Spline bundle until the page has rendered:

```jsx
import React, { Suspense } from "react";

const Spline = React.lazy(() => import("@splinetool/react-spline"));

export default function App() {
  return (
    <Suspense
      fallback={<div className="loading-placeholder">Loading 3D...</div>}
    >
      <Spline scene="https://prod.spline.design/YOUR_SCENE_ID/scene.splinecode" />
    </Suspense>
  );
}
```

## Full-Screen Background Pattern

To use Spline as a full-page background behind other UI (e.g., glassmorphism cards):

```jsx
import Spline from "@splinetool/react-spline";
import { Suspense } from "react";

export default function SplineBackground() {
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 0 }}>
      {/* Gradient fallback while loading */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(ellipse at top, rgba(49,46,129,0.4), rgba(88,28,135,0.2), black)",
          zIndex: 0,
        }}
      />

      <Suspense fallback={null}>
        <Spline
          style={{ width: "100%", height: "100%", opacity: 0.6 }}
          scene="https://prod.spline.design/YOUR_SCENE_ID/scene.splinecode"
        />
      </Suspense>
    </div>
  );
}
```

Then layer your UI on top with `position: relative; z-index: 10;`.

---

## Reading & Modifying Spline Objects

Use the `onLoad` callback to get a reference to the Spline application:

```jsx
import { useRef } from "react";
import Spline from "@splinetool/react-spline";

export default function App() {
  const cubeRef = useRef();

  function onLoad(splineApp) {
    const obj = splineApp.findObjectByName("Cube");
    // or: splineApp.findObjectById('UUID-HERE');
    cubeRef.current = obj;
  }

  function moveObject() {
    if (cubeRef.current) {
      cubeRef.current.position.x += 10;
    }
  }

  return (
    <>
      <Spline scene="..." onLoad={onLoad} />
      <button onClick={moveObject}>Move Cube</button>
    </>
  );
}
```

> **Tip:** Right-click an object in the Spline editor → "Copy Development Object ID" to get its UUID.

## Listening to Spline Events

Attach event listeners directly as props:

```jsx
<Spline
  scene="..."
  onSplineMouseDown={(e) => {
    if (e.target.name === "Button") {
      console.log("Button clicked!");
    }
  }}
  onSplineMouseHover={(e) => console.log("Hovering:", e.target.name)}
/>
```

## Triggering Spline Animations from React

```jsx
const splineRef = useRef();

function onLoad(splineApp) {
  splineRef.current = splineApp;
}

function triggerAnimation() {
  splineRef.current.emitEvent('mouseHover', 'ObjectName');
}

<Spline scene="..." onLoad={onLoad} />
<button onClick={triggerAnimation}>Animate</button>
```

---

## API Reference

### `<Spline />` Component Props

| Prop                 | Type                            | Description                                  |
| -------------------- | ------------------------------- | -------------------------------------------- |
| `scene`              | `string`                        | **Required.** URL to the `.splinecode` file  |
| `onLoad`             | `(spline: Application) => void` | Called when scene finishes loading           |
| `renderOnDemand`     | `boolean`                       | Enable on-demand rendering (default: `true`) |
| `className`          | `string`                        | CSS class for the container                  |
| `style`              | `object`                        | Inline styles for the container              |
| `id`                 | `string`                        | HTML id attribute                            |
| `ref`                | `React.Ref<HTMLDivElement>`     | React ref to the container div               |
| `onSplineMouseDown`  | `(e: SplineEvent) => void`      | Mouse Down event                             |
| `onSplineMouseHover` | `(e: SplineEvent) => void`      | Mouse Hover event                            |
| `onSplineMouseUp`    | `(e: SplineEvent) => void`      | Mouse Up event                               |
| `onSplineKeyDown`    | `(e: SplineEvent) => void`      | Key Down event                               |
| `onSplineKeyUp`      | `(e: SplineEvent) => void`      | Key Up event                                 |
| `onSplineStart`      | `(e: SplineEvent) => void`      | Start event                                  |
| `onSplineLookAt`     | `(e: SplineEvent) => void`      | Look At event                                |
| `onSplineFollow`     | `(e: SplineEvent) => void`      | Follow event                                 |
| `onSplineScroll`     | `(e: SplineEvent) => void`      | Scroll event                                 |

### Spline App Methods

| Method             | Signature                         | Description            |
| ------------------ | --------------------------------- | ---------------------- |
| `emitEvent`        | `(eventName, nameOrUuid) => void` | Trigger a Spline event |
| `emitEventReverse` | `(eventName, nameOrUuid) => void` | Reverse a Spline event |
| `findObjectById`   | `(uuid) => SPEObject`             | Find object by UUID    |
| `findObjectByName` | `(name) => SPEObject`             | Find object by name    |
| `setZoom`          | `(zoom) => void`                  | Set camera zoom level  |

### Spline Event Types

| Event Name   | Editor Label |
| ------------ | ------------ |
| `mouseDown`  | Mouse Down   |
| `mouseHover` | Mouse Hover  |
| `mouseUp`    | Mouse Up     |
| `keyDown`    | Key Down     |
| `keyUp`      | Key Up       |
| `start`      | Start        |
| `lookAt`     | Look At      |
| `follow`     | Follow       |

---

## Performance Tips

1. **Always lazy-load** — Spline bundles are large (~500KB+). Use `React.lazy()`.
2. **Use `renderOnDemand={true}`** — Only re-renders when the scene changes (default).
3. **Lower scene complexity** — Reduce polygon count and texture sizes in the Spline editor.
4. **Self-host `.splinecode`** — Download and place in `public/` for faster loads and no CORS.
5. **Set opacity** — Using `opacity: 0.5–0.7` on the Spline container improves text readability when used as a background.

## Troubleshooting

| Issue                   | Solution                                                                          |
| ----------------------- | --------------------------------------------------------------------------------- |
| CORS errors             | Download `.splinecode` and self-host in `public/`                                 |
| Mouse events not firing | In Spline editor: Export → change mouse events from "local" to "global container" |
| Scene not rendering     | Ensure both `@splinetool/react-spline` AND `@splinetool/runtime` are installed    |
| Performance issues      | Enable lazy loading, reduce scene complexity, use `renderOnDemand`                |
