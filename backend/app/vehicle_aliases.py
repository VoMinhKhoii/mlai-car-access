"""Driver vocabulary mapped to catalogue models or explicitly disclosed size classes.

No model dimensions are invented here. Non-catalogue family names use the existing
conservative class envelope; the response must disclose that substitution.
"""
from __future__ import annotations
import re
from . import vehicles
from .osm import strip_accents

MOTORBIKE = re.compile(r'\b(?:xe\s*may|motorbike|motorcycle|scooter|honda\s+wave|xe\s+dap|bicycle)\b')
CLASS_ALIASES = [
    (r'\b(?:(?:mercedes(?:\s+benz)?|merc|mec)\s*)?glc(?:\s*\d{3})?\b', 'class-m', 'Mercedes GLC'),
    (r'\b(?:mercedes(?:\s+benz)?|merc|mec)\s*e(?:\s*\d{3}|\s*class)?\b|\be\s*(?:200|250|300|350)\b', 'class-m', 'Mercedes E-Class'),
    (r'\bbmw\s*x\s*3\b', 'class-m', 'BMW X3'),
    (r'\b(?:kia\s+)?sorento\b', 'class-m', 'Kia Sorento'),
    (r'\b(?:honda\s+)?cr\s*v\b', 'class-m', 'Honda CR-V'),
    (r'\b(?:hyundai\s+)?tucson\b', 'class-m', 'Hyundai Tucson'),
    (r'\b(?:xe\s*)?7\s*(?:cho|seater|seats?)\b', 'class-m', None),
    (r'\b(?:xe\s*)?16\s*(?:cho|seater|seats?)\b', 'class-xl', None),
    (r'\b(?:xe\s*)?ban\s*tai\b|\bpickup\s+truck\b', 'class-l', None),
    (r'\bxe\s+co\s+nho\b', 'class-xs', None),
    (r'\bxe\s+co\s+lon\b', 'class-l', None),
    (r'\bsedan\b', 'class-s', None), (r'\bsuv\b', 'class-m', None),
]


def normalized(text):
    return re.sub(r'[^a-z0-9]+', ' ', strip_accents(str(text))).strip()


def vehicle_match(text):
    """Return (id, disclosure, character span in normalized text), or None.

    Token boundaries keep City/VF3 out of arbitrary address substrings. Explicit
    manufacturer/model matches precede generic words such as SUV or pickup.
    """
    norm = normalized(text)
    fleet = vehicles.all_profiles()
    candidates = []
    for p in fleet.values():
        if p.kind != 'model':
            continue
        names = [normalized(p.label), normalized(p.id.split('-', 1)[-1])]
        if p.id == 'mercedes-benz-c-class':
            names += ['mercedes c class', 'c class']
        for name in names:
            # VF8 variants are selected explicitly below when only a family is given.
            match = re.search(r'(?<!\w)' + re.escape(name).replace(r'\ ', r'\s*') + r'(?!\w)', norm)
            if match:
                if name in ('city', 'morning', 'territory') and match.start() > 0 and not re.search(r'(?:xe|lai|drive)\s+$', norm[:match.start()]):
                    continue
                candidates.append((len(name), p.id, None, match.span()))
    family = re.search(r'\b(?:vinfast\s*)?vf\s*([356789])\b', norm)
    if family:
        number = family[1]
        old_vf8 = number == '8' and bool(re.search(r'\b202[2-5]\b', norm))
        vid = ('vinfast-vf-8-2022-2025-generation' if old_vf8 else 'vinfast-vf-8-the-all-new-2026') if number == '8' else f'vinfast-vf-{number}'
        if vid in fleet:
            note = 'VF 8 model year is unspecified; temporarily using the catalogue specs for VF 8 The All New (2026).' if number == '8' and not re.search(r'\b202[2-6]\b', norm) else None
            candidates.append((20, vid, note, family.span()))
    cclass = re.search(r'\b(?:(?:mercedes(?:\s+benz)?|merc|mec)\s*)?c\s*(?:180|200|250|300|class)\b', norm)
    cclass = cclass or re.search(r'\b(?:mercedes(?:\s+benz)?|merc|mec)\s+c\b', norm)
    if cclass:
        candidates.append((20, 'mercedes-benz-c-class', 'Using catalogue Mercedes-Benz C-Class specs; the exact variant has not been verified.', cclass.span()))
    if candidates:
        _, vid, note, span = max(candidates, key=lambda x:x[0])
        return vid, note, span
    for pattern, vid, family_name in CLASS_ALIASES:
        m = re.search(pattern, norm)
        if m:
            note = (f'{family_name} has no dedicated catalogue specs; temporarily using size class '
                    f'{vid.split("-")[1].upper()} with a conservative size envelope. The exact variant has not been verified.') if family_name else None
            return vid, note, m.span()
    return None


def resolve_vehicle(value):
    value = str(value).strip()
    if value in vehicles.all_profiles():
        return value, None
    if MOTORBIKE.search(normalized(value)):
        raise ValueError('AlleyAI currently estimates car access; motorcycles and bicycles are not supported.')
    match = vehicle_match(value)
    if match:
        return match[0], match[1]
    raise ValueError('Vehicle not recognized. Please give the model or select a vehicle from the catalogue.')
