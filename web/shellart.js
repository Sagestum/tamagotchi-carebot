/* The drawings of the devices (web/shells, from BrickEmuPy) brought to life: every pixel and
   icon in them is an element named after its place in the display memory. For the page that
   only shows the pets; the page with the buttons has the same tables in index.html. */
const ART = {p1: 'p1w', p1j: 'p1', p2: 'p2', angel: 'angel', morino: 'morino', umino: 'umino', mothra: 'mothra',
             genjin: 'genjin', tamaotch: 'tamaotch', digimon: 'digimon', digimon2: 'digimon2', digimon3: 'digimon3',
             yasashii: 'yasashii', pikachu: 'pikachu'};
const KIN = {digimon2: 'digimon', digimon3: 'digimon'};
const kin = (model) => KIN[model] || model;
const BACKDROP = {p1: ['layout'], p1w: ['layout'], p2: ['layout'], angel: ['Vector 32', 'Vector 31'], morino: ['reflector'],
                  umino: ['reflector'], mothra: ['Vector_4'], genjin: ['reflector'], tamaotch: ['backdrop'], yasashii: ['reflector']};
const SEG_X = [0, 1, 2, 3, 4, 5, 6, 7, 32, 8, 9, 10, 11, 12, 13, 14, 15, 33, 34, 35, 31, 30, 29, 28, 27, 26,
               25, 24, 36, 23, 22, 21, 20, 19, 18, 17, 16, 37, 38, 39];
const P1_PINS = [[8, 0], [8, 1], [8, 2], [8, 3], [28, 12], [28, 13], [28, 14], [28, 15]];
const UMINO_PINS = [[8, 0], [17, 0], [18, 0], [19, 0], [39, 15], [38, 15], [37, 15], [28, 15]];
const PINS = {umino: UMINO_PINS, mothra: UMINO_PINS, genjin: UMINO_PINS, tamaotch: UMINO_PINS,
              digimon: [[28, 15], [37, 15], [38, 15], [39, 15], [11, 0], [10, 0], [9, 0], [0, 0]],
              yasashii: [[40, 8], [40, 12], [41, 8], [43, 8], [42, 12], [42, 8], [50, 8], [50, 12]]};
const LCD_OF = {digimon: {seg: [-1, 31, 30, 29, 28, 27, 26, 25, 24, -1, -1, -1, 23, 22, 21, 20, 19, 18, 17, 16, 0, 1, 2, 3, 4, 5, 6, 7, -1,
                               8, 9, 10, 11, 12, 13, 14, 15, -1, -1, -1], flip: true},
                yasashii: {seg: [31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16,
                                 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], flip: true}};

/* Puts the drawing of a model into box and returns draw(lcd, icons), which lights it as the
   server says: for a Tamagotchi 16 rows of 32 dots in hex and the icons as bits, for the
   Pocket Pikachu its LCD memory. */
function mountShell(box, text, model) {
  box.innerHTML = text;
  const svg = box.querySelector('svg');
  svg.setAttribute('role', 'img');
  let lastLcd = null, lastIcons = null;
  if (model === 'pikachu') {
    const els = new Array(176 * 8), on = new Uint8Array(176 * 8);
    for (const el of svg.querySelectorAll('[id]')) {
      const m = /^(\d+)_(\d)$/.exec(el.id);
      if (!m) continue;
      el.classList.add('seg');
      els[+m[1] * 8 + +m[2]] = el;
    }
    return (hex) => {
      if (hex === lastLcd) return;
      lastLcd = hex;
      for (let i = 0; i < els.length; i++) {
        if (!els[i]) continue;
        const bit = hex ? (parseInt(hex.substr((i >> 3) * 2, 2), 16) >> (i & 7)) & 1 : 0;
        if (on[i] !== bit) { on[i] = bit; els[i].classList.toggle('on', !!bit); }
      }
    };
  }
  const pins = PINS[kin(model)] || P1_PINS, pixels = new Array(512), icons = new Array(8), wiring = LCD_OF[kin(model)];
  for (const el of svg.querySelectorAll('[id]')) {
    const m = /^(\d+)_(\d)$/.exec(el.id);
    if (!m) continue;
    const n = +m[1], seg = (n < 80 ? n : n - 80) >> 1, com = (n >= 80 ? 8 : 0) + (n % 2) * 4 + +m[2];
    const icon = pins.findIndex(([s, c]) => s === seg && c === com);
    el.classList.add('seg');
    if (icon >= 0) icons[icon] = el;
    else if (wiring) { if (wiring.seg[seg] >= 0) pixels[(15 - com) * 32 + wiring.seg[seg]] = el; }
    else if (SEG_X[seg] < 32) pixels[com * 32 + SEG_X[seg]] = el;
  }
  for (const id of BACKDROP[ART[kin(model)]] || []) {
    const el = svg.querySelector(`[id="${id}"]`);
    if (el) el.setAttribute('opacity', (el.getAttribute('opacity') || 1) * 0.5);
  }
  const pixOn = new Uint8Array(512);
  return (hex, bits) => {
    if (hex !== lastLcd && hex.length === 128) {
      lastLcd = hex;
      for (let y = 0; y < 16; y++) {
        const row = parseInt(hex.substr(y * 8, 8), 16);
        for (let x = 0; x < 32; x++) {
          const bit = (row >>> (31 - x)) & 1, i = y * 32 + x;
          if (pixels[i] && pixOn[i] !== bit) { pixOn[i] = bit; pixels[i].classList.toggle('on', !!bit); }
        }
      }
    }
    if (bits !== lastIcons) {
      lastIcons = bits;
      icons.forEach((el, i) => el && el.classList.toggle('on', !!((bits >> i) & 1)));
    }
  };
}
