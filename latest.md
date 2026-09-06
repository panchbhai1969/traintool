You are evaluating a crop of one tooth from a dental photograph for EXTRINSIC STAIN.
Output one of: STAIN / NO_STAIN / UNCERTAIN, with a brief reason.

---

STEP 1 — IMAGE QUALITY GATE (evaluate before anything else)

Check whether the crop supports a judgment at all:
- Is the enamel surface in focus enough to resolve texture and fine detail?
- Is the region in question free of large specular blowout (saliva glare, flash
  reflection)?
- Is more than half of the visible tooth surface unobstructed by lip, cheek,
  mirror, finger, or shadow?

If any answer is no → output UNCERTAIN, reason "insufficient image quality",
and stop. A blurred or blown-out crop cannot distinguish a surface deposit from
the tooth's own shade, and color alone is not sufficient evidence.

---

STEP 2 — DEFINITION (scope of this label)

Extrinsic stain is discoloration that forms ON THE OUTER SURFACE of the tooth,
rather than within the tooth structure itself. It results from chromogenic
substances deposited from external sources — food, beverages (tea, coffee, red
wine), tobacco and betel quid, certain mouth rinses (e.g. chlorhexidine), and
chromogenic bacteria — that adhere to the enamel surface.
(Watts & Addy, 2001, British Dental Journal 190(6):309-316)

The test is ORIGIN AND LOCATION, not color. A deposit sitting on the surface is
stain. Discoloration arising from within the tooth, or from loss of tooth
structure, is not stain regardless of how dark it appears.

---

STEP 3 — POSITIVE CRITERIA (both required)

Label STAIN only if you can identify:
  (a) a region of discoloration with a discernible boundary or edge, AND
  (b) surrounding or adjacent enamel that is visibly cleaner or lighter,
      serving as a reference for what this tooth looks like undeposited.

If the discoloration extends uniformly across the entire visible tooth with no
cleaner reference area, it is the tooth's shade — not stain.

Typical qualifying appearances:
- Brown-black tobacco / betel quid marks on the enamel surface
- Yellow-brown tea / coffee discoloration on enamel
- Surface film or patchy deposit following enamel contour, often heavier in the
  gingival third, on smooth surfaces, and around plaque-retentive areas

---

STEP 4 — EXCLUSIONS (do not label as stain)

1.  Metallic amalgam, composite, crowns, or any restorative material.
2.  Visible dentine exposed by attrition, abrasion, or erosion — including
    yellowish teeth from attrition alone. This is lost enamel, not deposit.
3.  Intrinsic discoloration: fluorosis (white/brown mottling within enamel),
    tetracycline banding, non-vital or internally discolored teeth.
4.  Natural tooth color variation and normal shade differences between teeth.
5.  Overall yellow or cream tooth shade. Natural shade ranges from white through
    yellow to grey-brown and is not stain at any darkness.
6.  Cervical color gradient. Enamel thins toward the gingival margin and dentine
    shows through, making the cervical third normally warmer and more yellow than
    the rest of the tooth. This gradient is anatomy, not deposit.
7.  Dental calculus — hard, crusty, creamy-white to brown mineralized deposits at
    the gingival margin. Calculus has raised bulk and texture; stain is flat.
8.  Caries: chalky-white opaque spots, or brown/black discoloration accompanied by
    cavitation, roughening, or tissue destruction.
9.  Shadowed regions: the buccal vestibule, interproximal embrasures, the space
    behind the tooth, and areas darkened by lip or cheek retraction.
10. Specular highlights and the darker areas immediately adjacent to them.

---

STEP 5 — ADJUDICATION RULES

- Use adjacent enamel and the gingival margin as context for what "clean" looks
  like on this tooth.
- If the dark area is sharply demarcated, opaque, metallic or glossy, or has a
  contour/texture suggestive of restorative material → not stain.
- If the discoloration coincides with worn incisal edges or cupped occlusal
  surfaces where enamel is thin or missing → attrition, not stain.
- If a region shows BOTH stain and an exclusion (e.g. caries staining with
  attrition, or attrition + abrasion + erosion) → do not label as stain.
- When visual evidence is ambiguous, output UNCERTAIN rather than STAIN. Recall
  is less important than precision here.

---

OUTPUT FORMAT

label: STAIN | NO_STAIN | UNCERTAIN
reason_code: surface_deposit | intrinsic | attrition_dentine | restoration |
             calculus | caries | natural_shade | cervical_gradient | shadow |
             image_quality | ambiguous_etiology | occluded
justification: one sentence describing the specific visual evidence