/**
 * Unit tests for template.ts
 *
 * Tests Handlebars template rendering and utilities.
 */

import { describe, it, expect, beforeEach } from "vitest";
import {
  isFileTemplate,
  extractFilePath,
  renderTemplate,
  clearTemplateCache,
  registerHelper,
  registerPartial,
} from "../template.js";

describe("isFileTemplate", () => {
  it("should return true for file:// templates", () => {
    expect(isFileTemplate("file://path/to/template.hbs")).toBe(true);
    expect(isFileTemplate("file://template.txt")).toBe(true);
    expect(isFileTemplate("file://./relative/path.hbs")).toBe(true);
  });

  it("should return false for inline templates", () => {
    expect(isFileTemplate("Hello {{name}}!")).toBe(false);
    expect(isFileTemplate("Just plain text")).toBe(false);
    expect(isFileTemplate("")).toBe(false);
  });

  it("should return false for file-like but not file:// templates", () => {
    expect(isFileTemplate("filepath://test")).toBe(false);
    expect(isFileTemplate("File://test")).toBe(false); // case sensitive
    expect(isFileTemplate(" file://test")).toBe(false); // leading space
  });
});

describe("extractFilePath", () => {
  it("should extract path from file:// template", () => {
    expect(extractFilePath("file://path/to/template.hbs")).toBe("path/to/template.hbs");
    expect(extractFilePath("file://template.txt")).toBe("template.txt");
    expect(extractFilePath("file:///absolute/path.hbs")).toBe("/absolute/path.hbs");
  });

  it("should throw for non-file templates", () => {
    expect(() => extractFilePath("Hello {{name}}")).toThrow("Not a file template");
    expect(() => extractFilePath("")).toThrow("Not a file template");
  });
});

describe("renderTemplate", () => {
  beforeEach(() => {
    clearTemplateCache();
  });

  describe("inline templates", () => {
    it("should render simple variable substitution", async () => {
      const result = await renderTemplate("Hello {{name}}!", { name: "World" });
      expect(result).toBe("Hello World!");
    });

    it("should render multiple variables", async () => {
      const result = await renderTemplate(
        "{{greeting}}, {{name}}! You have {{count}} messages.",
        { greeting: "Hi", name: "User", count: 5 }
      );
      expect(result).toBe("Hi, User! You have 5 messages.");
    });

    it("should handle missing variables as empty", async () => {
      const result = await renderTemplate("Hello {{name}}!", {});
      expect(result).toBe("Hello !");
    });

    it("should render nested object properties", async () => {
      const result = await renderTemplate("Name: {{user.name}}, Age: {{user.age}}", {
        user: { name: "John", age: 30 },
      });
      expect(result).toBe("Name: John, Age: 30");
    });

    it("should render arrays with #each", async () => {
      const result = await renderTemplate(
        "Items: {{#each items}}{{this}}{{#unless @last}}, {{/unless}}{{/each}}",
        { items: ["a", "b", "c"] }
      );
      expect(result).toBe("Items: a, b, c");
    });

    it("should handle conditionals", async () => {
      const template = "{{#if active}}Active{{else}}Inactive{{/if}}";

      const activeResult = await renderTemplate(template, { active: true });
      expect(activeResult).toBe("Active");

      const inactiveResult = await renderTemplate(template, { active: false });
      expect(inactiveResult).toBe("Inactive");
    });

    it("should render empty string for empty template", async () => {
      const result = await renderTemplate("", {});
      expect(result).toBe("");
    });

    it("should preserve literal text", async () => {
      const result = await renderTemplate("No variables here.", {});
      expect(result).toBe("No variables here.");
    });
  });

  describe("built-in helpers", () => {
    it("should use json helper", async () => {
      // Use triple braces to avoid HTML escaping
      const result = await renderTemplate("Data: {{{json data}}}", {
        data: { key: "value" },
      });
      expect(result).toContain('"key": "value"');
    });

    it("should use join helper", async () => {
      const result = await renderTemplate("Items: {{join items ', '}}", {
        items: ["a", "b", "c"],
      });
      expect(result).toBe("Items: a, b, c");
    });

    it("should handle join with non-array", async () => {
      const result = await renderTemplate("Items: {{join notArray ', '}}", {
        notArray: "string",
      });
      expect(result).toBe("Items: ");
    });

    it("should use eq helper", async () => {
      const template = "{{#if (eq status 'active')}}Yes{{else}}No{{/if}}";

      const activeResult = await renderTemplate(template, { status: "active" });
      expect(activeResult).toBe("Yes");

      const otherResult = await renderTemplate(template, { status: "inactive" });
      expect(otherResult).toBe("No");
    });

    it("should use ne helper", async () => {
      const template = "{{#if (ne value 0)}}Non-zero{{else}}Zero{{/if}}";

      const nonZero = await renderTemplate(template, { value: 5 });
      expect(nonZero).toBe("Non-zero");

      const zero = await renderTemplate(template, { value: 0 });
      expect(zero).toBe("Zero");
    });

    it("should use default helper", async () => {
      const template = "Name: {{default name 'Anonymous'}}";

      const withName = await renderTemplate(template, { name: "John" });
      expect(withName).toBe("Name: John");

      const withoutName = await renderTemplate(template, {});
      expect(withoutName).toBe("Name: Anonymous");
    });
  });

  describe("template caching", () => {
    it("should cache compiled templates", async () => {
      const template = "Hello {{name}}!";

      // First render - compiles template
      const result1 = await renderTemplate(template, { name: "First" });
      expect(result1).toBe("Hello First!");

      // Second render - uses cache
      const result2 = await renderTemplate(template, { name: "Second" });
      expect(result2).toBe("Hello Second!");
    });

    it("should clear cache", async () => {
      const template = "Hello {{name}}!";

      await renderTemplate(template, { name: "Test" });
      clearTemplateCache();

      // Should work after cache clear
      const result = await renderTemplate(template, { name: "After Clear" });
      expect(result).toBe("Hello After Clear!");
    });
  });
});

describe("registerHelper", () => {
  beforeEach(() => {
    clearTemplateCache();
  });

  it("should register and use custom helper", async () => {
    registerHelper("uppercase", (str: string) => str.toUpperCase());

    const result = await renderTemplate("Name: {{uppercase name}}", { name: "john" });
    expect(result).toBe("Name: JOHN");
  });

  it("should register helper with multiple arguments", async () => {
    registerHelper("repeat", (str: string, times: number) => {
      return str.repeat(typeof times === "number" ? times : 1);
    });

    const result = await renderTemplate("{{repeat text 3}}", { text: "Hi" });
    expect(result).toBe("HiHiHi");
  });
});

describe("registerPartial", () => {
  beforeEach(() => {
    clearTemplateCache();
  });

  it("should register and use partial template", async () => {
    registerPartial("header", "<h1>{{title}}</h1>");

    const result = await renderTemplate("{{> header title='Welcome'}}", {});
    expect(result).toBe("<h1>Welcome</h1>");
  });

  it("should use partial with context", async () => {
    registerPartial("userCard", "User: {{name}} ({{role}})");

    const result = await renderTemplate("{{> userCard}}", {
      name: "John",
      role: "Admin",
    });
    expect(result).toBe("User: John (Admin)");
  });
});
