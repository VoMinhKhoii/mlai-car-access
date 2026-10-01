import json, collections, re, sys
for fn in sys.argv[1:]:
    d=json.load(open(fn)); els=d['elements']
    hn=[e['tags'].get('addr:housenumber','') for e in els]
    st=[e['tags'].get('addr:street','') for e in els]
    slash=[h for h in hn if '/' in h]
    depth=collections.Counter(h.count('/') for h in hn)
    stp=collections.Counter((s.split()[0] if s else '(none)') for s in st)
    print('=====',fn,'addr objects',len(els),' by type',collections.Counter(e['type'] for e in els))
    print('  housenumber slash-depth:',sorted(depth.items()))
    print('  e.g. slash housenumbers:',[ (e['tags'].get('addr:housenumber'),e['tags'].get('addr:street')) for e in els if '/' in e['tags'].get('addr:housenumber','')][:8])
    print('  addr:street first word:',stp.most_common(8))
    ex=[(e['tags'].get('addr:housenumber'),e['tags'].get('addr:street')) for e in els if re.match(r'^(Ngõ|Ngách|Hẻm)',e['tags'].get('addr:street',''))][:10]
    print('  alley-street examples:',ex)
    print('  with building tag:', sum(1 for e in els if 'building' in e['tags']))
