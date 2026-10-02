"""Erzeugt STL-Dateien für das Meeting-KI-Gehäuse (ESP32-C3 Super Mini +
INMP441 ohne Pinleiste + LiPo-Akku 20x27x5 mm).

Dieses Skript nutzt trimesh/manifold3d und ist unabhängig von FreeCAD – es dient
dazu, direkt druckfertige STLs zu erzeugen. Die gleiche Geometrie gibt es als
parametrisches FreeCAD-Macro in `meeting_ki_case.FCMacro` (zum Bearbeiten).

Aufruf:  python generate_case.py
Ergebnis: base.stl (Unterteil) und lid.stl (Deckel) im selben Ordner.

ALLE Maße in Millimetern. Bitte an deinen echten Bauteilen prüfen und ggf. oben
anpassen – die Elektronik-Außenmaße variieren je nach Hersteller leicht.
"""
import os

import numpy as np
import trimesh

# ------------------------------------------------------------------ Parameter
WALL   = 2.0    # Wandstärke
FLOOR  = 1.5    # Bodendicke
LIDTOP = 1.5    # Deckeldicke

# Innenraum (netto nutzbar)
IN_L = 29.0     # Länge (X)
IN_W = 21.0     # Breite (Y)
IN_H = 15.0     # Höhe (Z) vom Boden bis Deckelunterkante

# Akku (liegt unten auf dem Boden)
BATT_H = 5.0

# Auflage-Schienen für die ESP-Platine (an den langen Wänden)
RAIL_W   = 2.5                       # wie weit die Schiene nach innen ragt
RAIL_T   = 1.5                       # Dicke der Schiene
RAIL_TOP = FLOOR + BATT_H + 1.0      # Oberkante Schiene = Auflage der Platine

# USB-C-Ausschnitt (in einer Schmalseite, +X-Wand)
USB_W = 12.0
USB_H = 6.0
USB_Z = RAIL_TOP + 1.8               # Mitte des Ausschnitts (ca. Platinenmitte)

# Deckel-Rand (Steckrand, der innen in das Unterteil greift -> Reibschluss)
RIM_CLEAR = 0.3     # Spiel zum Innenmaß
RIM_T     = 1.5     # Dicke des Stegs
RIM_H     = 4.0     # Höhe des Stegs

# Mikrofon-Aufnahme im Deckel (INMP441 ohne Pinleiste, liegt unter dem Deckel)
MIC_L = 15.0
MIC_W = 13.0
MIC_POCKET_DEPTH = 2.2     # Vertiefung an der Deckelunterseite für das Mic-Board
MIC_HOLE_D = 3.0           # Schallloch durch den Deckel
# Position (relativ zur Deckelmitte): ans gegenüberliegende Ende vom USB-C
MIC_OFFSET_X = -IN_L / 2 + MIC_L / 2 + 1.0

# Bedien-/Anzeige-Öffnungen im Deckel
BTN_HOLE_D = 3.5           # Zugang zum Taster (drücken mit Finger/Stift)
BTN_OFFSET_X = IN_L / 2 - 6.0
LED_HOLE_D = 2.2           # Lichtleiter-/Sichtloch für die Status-LED
LED_OFFSET_X = IN_L / 2 - 11.0

# Außenmaße
OUT_L = IN_L + 2 * WALL
OUT_W = IN_W + 2 * WALL
BASE_H = FLOOR + IN_H      # Höhe des Unterteils (oben offen)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def box(size, center):
    """Achsparalleler Quader mit Größe=size, zentriert auf center."""
    T = trimesh.transformations.translation_matrix(center)
    return trimesh.creation.box(extents=size, transform=T)


def cyl(radius, height, center, axis="z"):
    m = trimesh.creation.cylinder(radius=radius, height=height, sections=48)
    if axis == "y":
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    m.apply_translation(center)
    return m


def build_base():
    cx, cy = OUT_L / 2, OUT_W / 2

    # Voller Außenkörper
    outer = box([OUT_L, OUT_W, BASE_H], [cx, cy, BASE_H / 2])

    # Innenkavität (oben offen): von FLOOR bis oben
    cavity = box([IN_L, IN_W, IN_H + 1.0],
                 [cx, cy, FLOOR + (IN_H + 1.0) / 2])
    base = outer.difference(cavity)

    # Auflage-Schienen an den beiden langen Wänden (Y-min und Y-max)
    rail_cz = RAIL_TOP - RAIL_T / 2
    rail_y1 = WALL + RAIL_W / 2
    rail_y2 = OUT_W - WALL - RAIL_W / 2
    rail1 = box([IN_L, RAIL_W, RAIL_T], [cx, rail_y1, rail_cz])
    rail2 = box([IN_L, RAIL_W, RAIL_T], [cx, rail_y2, rail_cz])
    base = base.union(rail1).union(rail2)

    # USB-C-Ausschnitt in der +X-Schmalseite
    usb = box([WALL * 3, USB_W, USB_H], [OUT_L - WALL, cy, USB_Z])
    base = base.difference(usb)

    return base


def build_lid():
    cx, cy = OUT_L / 2, OUT_W / 2

    # Deckelplatte
    plate = box([OUT_L, OUT_W, LIDTOP], [cx, cy, LIDTOP / 2])

    # Steckrand (innen, greift ins Unterteil)
    rim_outer = box([IN_L - 2 * RIM_CLEAR, IN_W - 2 * RIM_CLEAR, RIM_H],
                    [cx, cy, LIDTOP + RIM_H / 2])
    rim_inner = box([IN_L - 2 * RIM_CLEAR - 2 * RIM_T,
                     IN_W - 2 * RIM_CLEAR - 2 * RIM_T, RIM_H + 1],
                    [cx, cy, LIDTOP + RIM_H / 2])
    rim = rim_outer.difference(rim_inner)
    lid = plate.union(rim)

    # Mikrofon-Tasche an der Unterseite (Vertiefung für das INMP441-Board)
    mic_cx = cx + MIC_OFFSET_X
    pocket = box([MIC_L, MIC_W, MIC_POCKET_DEPTH],
                 [mic_cx, cy, LIDTOP + MIC_POCKET_DEPTH / 2 - 0.001])
    lid = lid.difference(pocket)

    # Durchgangslöcher im Deckel: Schallloch, Taster, LED
    holes = [
        cyl(MIC_HOLE_D / 2, LIDTOP * 4, [mic_cx, cy, LIDTOP / 2]),
        cyl(BTN_HOLE_D / 2, LIDTOP * 4, [cx + BTN_OFFSET_X, cy, LIDTOP / 2]),
        cyl(LED_HOLE_D / 2, LIDTOP * 4, [cx + LED_OFFSET_X, cy, LIDTOP / 2]),
    ]
    for h in holes:
        lid = lid.difference(h)

    return lid


def main():
    base = build_base()
    lid = build_lid()

    base_path = os.path.join(OUT_DIR, "base.stl")
    lid_path = os.path.join(OUT_DIR, "lid.stl")
    base.export(base_path)
    lid.export(lid_path)

    # Zusammenbau-Vorschau (Deckel aufgesetzt, gespiegelt oben drauf)
    lid_preview = lid.copy()
    lid_preview.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    lid_preview.apply_translation([0, OUT_W, BASE_H + LIDTOP])
    assembly = trimesh.util.concatenate([base, lid_preview])
    assembly.export(os.path.join(OUT_DIR, "assembly_preview.stl"))

    print(f"Außenmaße Unterteil: {OUT_L:.1f} x {OUT_W:.1f} x {BASE_H:.1f} mm")
    print(f"Mit Deckel gesamt:   {OUT_L:.1f} x {OUT_W:.1f} x {BASE_H + LIDTOP:.1f} mm")
    print(f"base watertight: {base.is_watertight} | vol {base.volume/1000:.2f} cm^3")
    print(f"lid  watertight: {lid.is_watertight} | vol {lid.volume/1000:.2f} cm^3")
    print(f"geschrieben: {base_path}")
    print(f"geschrieben: {lid_path}")


if __name__ == "__main__":
    main()
