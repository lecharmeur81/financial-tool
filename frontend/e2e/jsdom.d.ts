// jsdom ships no types and the project adds no @types package; this declares only what the
// Phase 56 harness uses (parsing a server-rendered HTML string into a Document).
declare module "jsdom" {
  export class JSDOM {
    constructor(html?: string);
    readonly window: { readonly document: Document };
  }
}
