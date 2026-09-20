// src/filter.ts
var ExplicitPublish = () => ({
  name: "ExplicitPublish",
  shouldPublish(_ctx, [_tree, vfile]) {
    const frontmatter = vfile.data?.frontmatter;
    return frontmatter?.publish === true || frontmatter?.publish === "true";
  }
});

export { ExplicitPublish };
//# sourceMappingURL=index.js.map
//# sourceMappingURL=index.js.map