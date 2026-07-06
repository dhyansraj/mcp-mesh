import { describe, it, expect } from "vitest";
import { splitServiceCapability, groupByService } from "../lib/service-group";

describe("splitServiceCapability", () => {
  it("splits on the last dot", () => {
    expect(splitServiceCapability("media.caption")).toEqual({
      service: "media",
      method: "caption",
    });
  });

  it("uses the LAST dot for multi-segment names", () => {
    expect(splitServiceCapability("a.b.c")).toEqual({
      service: "a.b",
      method: "c",
    });
  });

  it("treats an undotted name as ungrouped", () => {
    expect(splitServiceCapability("greet")).toEqual({
      service: "",
      method: "greet",
    });
  });

  it("treats a leading-dot name as ungrouped (empty service segment)", () => {
    expect(splitServiceCapability(".caption")).toEqual({
      service: "",
      method: ".caption",
    });
  });

  it("treats a trailing-dot name as ungrouped (empty method segment)", () => {
    expect(splitServiceCapability("media.")).toEqual({
      service: "",
      method: "media.",
    });
  });
});

interface NamedItem {
  name: string;
}

const named = (name: string): NamedItem => ({ name });

describe("groupByService", () => {
  it("groups dotted items by service and leaves undotted ungrouped", () => {
    const items = [named("media.thumbnail"), named("greet"), named("media.caption")];
    const { services, ungrouped } = groupByService(items, (i) => i.name);

    expect(services).toHaveLength(1);
    expect(services[0].name).toBe("media");
    expect(services[0].items.map((i) => i.name)).toEqual([
      "media.caption",
      "media.thumbnail",
    ]);
    expect(ungrouped.map((i) => i.name)).toEqual(["greet"]);
  });

  it("sorts services by name", () => {
    const items = [named("zeta.a"), named("alpha.b"), named("media.c")];
    const { services } = groupByService(items, (i) => i.name);
    expect(services.map((s) => s.name)).toEqual(["alpha", "media", "zeta"]);
  });

  it("sorts methods within a service by method name", () => {
    const items = [named("media.thumbnail"), named("media.caption"), named("media.blur")];
    const { services } = groupByService(items, (i) => i.name);
    expect(services[0].items.map((i) => i.name)).toEqual([
      "media.blur",
      "media.caption",
      "media.thumbnail",
    ]);
  });

  it("sorts the ungrouped bucket by name", () => {
    const items = [named("zzz"), named("aaa"), named("mmm")];
    const { ungrouped } = groupByService(items, (i) => i.name);
    expect(ungrouped.map((i) => i.name)).toEqual(["aaa", "mmm", "zzz"]);
  });

  it("uses byte-order comparison, not localeCompare (uppercase sorts before lowercase)", () => {
    // Byte order: 'B' (0x42) < 'a' (0x61). localeCompare would order these the
    // other way, so this asserts parity with the CLI's sort.Strings.
    const items = [named("svc.apple"), named("svc.Banana")];
    const { services } = groupByService(items, (i) => i.name);
    expect(services[0].items.map((i) => i.name)).toEqual([
      "svc.Banana",
      "svc.apple",
    ]);
  });

  it("returns empty groupings for an empty input", () => {
    const { services, ungrouped } = groupByService<NamedItem>([], (i) => i.name);
    expect(services).toEqual([]);
    expect(ungrouped).toEqual([]);
  });
});
