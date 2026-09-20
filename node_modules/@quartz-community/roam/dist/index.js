// node_modules/unist-util-is/lib/index.js
var convert = (
  // Note: overloads in JSDoc can’t yet use different `@template`s.
  /**
   * @type {(
   *   (<Condition extends string>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & {type: Condition}) &
   *   (<Condition extends Props>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & Condition) &
   *   (<Condition extends TestFunction>(test: Condition) => (node: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node & Predicate<Condition, Node>) &
   *   ((test?: null | undefined) => (node?: unknown, index?: number | null | undefined, parent?: Parent | null | undefined, context?: unknown) => node is Node) &
   *   ((test?: Test) => Check)
   * )}
   */
  /**
   * @param {Test} [test]
   * @returns {Check}
   */
  (function(test) {
    if (test === null || test === void 0) {
      return ok;
    }
    if (typeof test === "function") {
      return castFactory(test);
    }
    if (typeof test === "object") {
      return Array.isArray(test) ? anyFactory(test) : (
        // Cast because `ReadonlyArray` goes into the above but `isArray`
        // narrows to `Array`.
        propertiesFactory(
          /** @type {Props} */
          test
        )
      );
    }
    if (typeof test === "string") {
      return typeFactory(test);
    }
    throw new Error("Expected function, string, or object as test");
  })
);
function anyFactory(tests) {
  const checks = [];
  let index = -1;
  while (++index < tests.length) {
    checks[index] = convert(tests[index]);
  }
  return castFactory(any);
  function any(...parameters) {
    let index2 = -1;
    while (++index2 < checks.length) {
      if (checks[index2].apply(this, parameters)) return true;
    }
    return false;
  }
}
function propertiesFactory(check) {
  const checkAsRecord = (
    /** @type {Record<string, unknown>} */
    check
  );
  return castFactory(all);
  function all(node) {
    const nodeAsRecord = (
      /** @type {Record<string, unknown>} */
      /** @type {unknown} */
      node
    );
    let key;
    for (key in check) {
      if (nodeAsRecord[key] !== checkAsRecord[key]) return false;
    }
    return true;
  }
}
function typeFactory(check) {
  return castFactory(type);
  function type(node) {
    return node && node.type === check;
  }
}
function castFactory(testFunction) {
  return check;
  function check(value, index, parent) {
    return Boolean(
      looksLikeANode(value) && testFunction.call(
        this,
        value,
        typeof index === "number" ? index : void 0,
        parent || void 0
      )
    );
  }
}
function ok() {
  return true;
}
function looksLikeANode(value) {
  return value !== null && typeof value === "object" && "type" in value;
}

// node_modules/unist-util-visit-parents/lib/color.node.js
function color(d) {
  return "\x1B[33m" + d + "\x1B[39m";
}

// node_modules/unist-util-visit-parents/lib/index.js
var empty = [];
var CONTINUE = true;
var EXIT = false;
var SKIP = "skip";
function visitParents(tree, test, visitor, reverse) {
  let check;
  if (typeof test === "function" && typeof visitor !== "function") {
    reverse = visitor;
    visitor = test;
  } else {
    check = test;
  }
  const is2 = convert(check);
  const step = reverse ? -1 : 1;
  factory(tree, void 0, [])();
  function factory(node, index, parents) {
    const value = (
      /** @type {Record<string, unknown>} */
      node && typeof node === "object" ? node : {}
    );
    if (typeof value.type === "string") {
      const name = (
        // `hast`
        typeof value.tagName === "string" ? value.tagName : (
          // `xast`
          typeof value.name === "string" ? value.name : void 0
        )
      );
      Object.defineProperty(visit2, "name", {
        value: "node (" + color(node.type + (name ? "<" + name + ">" : "")) + ")"
      });
    }
    return visit2;
    function visit2() {
      let result = empty;
      let subresult;
      let offset;
      let grandparents;
      if (!test || is2(node, index, parents[parents.length - 1] || void 0)) {
        result = toResult(visitor(node, parents));
        if (result[0] === EXIT) {
          return result;
        }
      }
      if ("children" in node && node.children) {
        const nodeAsParent = (
          /** @type {UnistParent} */
          node
        );
        if (nodeAsParent.children && result[0] !== SKIP) {
          offset = (reverse ? nodeAsParent.children.length : -1) + step;
          grandparents = parents.concat(nodeAsParent);
          while (offset > -1 && offset < nodeAsParent.children.length) {
            const child = nodeAsParent.children[offset];
            subresult = factory(child, offset, grandparents)();
            if (subresult[0] === EXIT) {
              return subresult;
            }
            offset = typeof subresult[1] === "number" ? subresult[1] : offset + step;
          }
        }
      }
      return result;
    }
  }
}
function toResult(value) {
  if (Array.isArray(value)) {
    return value;
  }
  if (typeof value === "number") {
    return [CONTINUE, value];
  }
  return value === null || value === void 0 ? empty : [value];
}

// node_modules/unist-util-visit/lib/index.js
function visit(tree, testOrVisitor, visitorOrReverse, maybeReverse) {
  let reverse;
  let test;
  let visitor;
  {
    test = testOrVisitor;
    visitor = visitorOrReverse;
    reverse = maybeReverse;
  }
  visitParents(tree, test, overload, reverse);
  function overload(node, parents) {
    const parent = parents[parents.length - 1];
    const index = parent ? parent.children.indexOf(node) : void 0;
    return visitor(node, index, parent);
  }
}

// node_modules/mdast-util-find-and-replace/node_modules/escape-string-regexp/index.js
function escapeStringRegexp(string) {
  if (typeof string !== "string") {
    throw new TypeError("Expected a string");
  }
  return string.replace(/[|\\{}()[\]^$+*?.]/g, "\\$&").replace(/-/g, "\\x2d");
}

// node_modules/mdast-util-find-and-replace/lib/index.js
function findAndReplace(tree, list, options) {
  const settings = {};
  const ignored = convert(settings.ignore || []);
  const pairs = toPairs(list);
  let pairIndex = -1;
  while (++pairIndex < pairs.length) {
    visitParents(tree, "text", visitor);
  }
  function visitor(node, parents) {
    let index = -1;
    let grandparent;
    while (++index < parents.length) {
      const parent = parents[index];
      const siblings = grandparent ? grandparent.children : void 0;
      if (ignored(
        parent,
        siblings ? siblings.indexOf(parent) : void 0,
        grandparent
      )) {
        return;
      }
      grandparent = parent;
    }
    if (grandparent) {
      return handler(node, parents);
    }
  }
  function handler(node, parents) {
    const parent = parents[parents.length - 1];
    const find = pairs[pairIndex][0];
    const replace = pairs[pairIndex][1];
    let start = 0;
    const siblings = parent.children;
    const index = siblings.indexOf(node);
    let change = false;
    let nodes = [];
    find.lastIndex = 0;
    let match = find.exec(node.value);
    while (match) {
      const position = match.index;
      const matchObject = {
        index: match.index,
        input: match.input,
        stack: [...parents, node]
      };
      let value = replace(...match, matchObject);
      if (typeof value === "string") {
        value = value.length > 0 ? { type: "text", value } : void 0;
      }
      if (value === false) {
        find.lastIndex = position + 1;
      } else {
        if (start !== position) {
          nodes.push({
            type: "text",
            value: node.value.slice(start, position)
          });
        }
        if (Array.isArray(value)) {
          nodes.push(...value);
        } else if (value) {
          nodes.push(value);
        }
        start = position + match[0].length;
        change = true;
      }
      if (!find.global) {
        break;
      }
      match = find.exec(node.value);
    }
    if (change) {
      if (start < node.value.length) {
        nodes.push({ type: "text", value: node.value.slice(start) });
      }
      parent.children.splice(index, 1, ...nodes);
    } else {
      nodes = [node];
    }
    return index + nodes.length;
  }
}
function toPairs(tupleOrList) {
  const result = [];
  if (!Array.isArray(tupleOrList)) {
    throw new TypeError("Expected find and replace tuple or list of tuples");
  }
  const list = !tupleOrList[0] || Array.isArray(tupleOrList[0]) ? tupleOrList : [tupleOrList];
  let index = -1;
  while (++index < list.length) {
    const tuple = list[index];
    result.push([toExpression(tuple[0]), toFunction(tuple[1])]);
  }
  return result;
}
function toExpression(find) {
  return typeof find === "string" ? new RegExp(escapeStringRegexp(find), "g") : find;
}
function toFunction(replace) {
  return typeof replace === "function" ? replace : function() {
    return replace;
  };
}

// src/transformer.ts
var defaultOptions = {
  orComponent: true,
  TODOComponent: true,
  DONEComponent: true,
  videoComponent: true,
  audioComponent: true,
  pdfComponent: true,
  blockquoteComponent: true,
  tableComponent: true,
  attributeComponent: true
};
var orRegex = new RegExp(/{{or:(.*?)}}/, "g");
var TODORegex = new RegExp(/{{.*?\bTODO\b.*?}}/, "g");
var DONERegex = new RegExp(/{{.*?\bDONE\b.*?}}/, "g");
var blockquoteRegex = new RegExp(/(\[\[>\]\])\s*(.*)/, "g");
var roamHighlightRegex = new RegExp(/\^\^(.+)\^\^/, "g");
var roamItalicRegex = new RegExp(/__(.+)__/, "g");
function isSpecialEmbed(node) {
  if (node.children.length !== 2) return false;
  const [textNode, linkNode] = node.children;
  return !!(textNode && textNode.type === "text" && textNode.value.startsWith("{{[[") && linkNode && linkNode.type === "link" && linkNode.children && linkNode.children[0] && linkNode.children[0].type === "text" && linkNode.children[0].value.endsWith("}}"));
}
function transformSpecialEmbed(node, opts) {
  const [textNode, linkNode] = node.children;
  const embedType = textNode.value.match(/\{\{\[\[(.*?)\]\]:/)?.[1]?.toLowerCase();
  const url = linkNode.url.slice(0, -2);
  switch (embedType) {
    case "audio":
      return opts.audioComponent ? {
        type: "html",
        value: `<audio controls>
          <source src="${url}" type="audio/mpeg">
          <source src="${url}" type="audio/ogg">
          Your browser does not support the audio tag.
        </audio>`
      } : null;
    case "video": {
      if (!opts.videoComponent) return null;
      const youtubeMatch = url.match(
        /(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?(.+)/
      );
      if (youtubeMatch && youtubeMatch[1]) {
        const videoId = youtubeMatch[1].split("&")[0];
        const playlistMatch = url.match(/[?&]list=([^#&?]*)/);
        const playlistId = playlistMatch ? playlistMatch[1] : null;
        return {
          type: "html",
          value: `<iframe 
            class="external-embed youtube"
            width="600px"
            height="350px"
            src="https://www.youtube.com/embed/${videoId}${playlistId ? `?list=${playlistId}` : ""}"
            frameborder="0"
            allow="fullscreen"
          ></iframe>`
        };
      } else {
        return {
          type: "html",
          value: `<video controls>
            <source src="${url}" type="video/mp4">
            <source src="${url}" type="video/webm">
            Your browser does not support the video tag.
          </video>`
        };
      }
    }
    case "pdf":
      return opts.pdfComponent ? {
        type: "html",
        value: `<embed src="${url}" type="application/pdf" width="100%" height="600px" />`
      } : null;
    default:
      return null;
  }
}
var RoamFlavoredMarkdown = (userOpts) => {
  const opts = { ...defaultOptions, ...userOpts };
  return {
    name: "RoamFlavoredMarkdown",
    markdownPlugins() {
      const plugins = [];
      plugins.push(() => {
        return (tree) => {
          const replacements = [];
          if (opts.audioComponent || opts.videoComponent || opts.pdfComponent) {
            visit(tree, "paragraph", ((node, index, parent) => {
              if (isSpecialEmbed(node)) {
                const transformedNode = transformSpecialEmbed(node, opts);
                if (transformedNode && parent) {
                  parent.children[index] = transformedNode;
                }
              }
            }));
          }
          replacements.push([
            roamItalicRegex,
            (_value, match) => ({
              type: "emphasis",
              children: [{ type: "text", value: match }]
            })
          ]);
          replacements.push([
            roamHighlightRegex,
            (_value, inner) => ({
              type: "html",
              value: `<span class="text-highlight">${inner}</span>`
            })
          ]);
          if (opts.orComponent) {
            replacements.push([
              orRegex,
              (match) => {
                const matchResult = match.match(/{{or:(.*?)}}/);
                if (matchResult === null || !matchResult[1]) {
                  return { type: "html", value: "" };
                }
                const optionsString = matchResult[1];
                const options = optionsString.split("|");
                const selectHtml = `<select>${options.map((option) => `<option value="${option}">${option}</option>`).join("")}</select>`;
                return { type: "html", value: selectHtml };
              }
            ]);
          }
          if (opts.TODOComponent) {
            replacements.push([
              TODORegex,
              () => ({
                type: "html",
                value: `<input type="checkbox" disabled>`
              })
            ]);
          }
          if (opts.DONEComponent) {
            replacements.push([
              DONERegex,
              () => ({
                type: "html",
                value: `<input type="checkbox" checked disabled>`
              })
            ]);
          }
          if (opts.blockquoteComponent) {
            replacements.push([
              blockquoteRegex,
              (_match, _marker, content) => ({
                type: "html",
                value: `<blockquote>${content.trim()}</blockquote>`
              })
            ]);
          }
          findAndReplace(tree, replacements);
        };
      });
      return plugins;
    }
  };
};

export { RoamFlavoredMarkdown };
//# sourceMappingURL=index.js.map
//# sourceMappingURL=index.js.map