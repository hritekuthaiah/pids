interface ImportMetaEnv {
  /**
   * The edge node's annotated MJPEG preview, embedded in the console's camera panel.
   * Defaults to the edge's loopback address, http://127.0.0.1:8090/stream.mjpg (ADR-0011),
   * so the console must run on the same machine as the edge node.
   */
  readonly VITE_EDGE_PREVIEW_URL?: string;
}
