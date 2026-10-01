import sqlite3, struct, json, sys
from shapely import wkb
from shapely.ops import transform
from pyproj import Transformer, CRS

def gpkg_blob_to_geom(b):
    # GeoPackage binary header
    assert b[:2]==b'GP'
    flags=b[3]
    env_ind=(flags>>1)&7
    env_len={0:0,1:32,2:48,3:48,4:64}[env_ind]
    return wkb.loads(bytes(b[8+env_len:]))

def load(path, table, srs):
    con=sqlite3.connect(path)
    cur=con.execute(f'select * from "{table}"')
    cols=[d[0] for d in cur.description]
    crs=CRS.from_wkt(con.execute('select definition from gpkg_spatial_ref_sys where srs_id=?',(srs,)).fetchone()[0]) if srs!=4326 else CRS.from_epsg(4326)
    t=Transformer.from_crs(CRS.from_epsg(srs), CRS.from_epsg(4326), always_xy=True)
    feats=[]
    for row in cur:
        props={}
        g=None
        for c,v in zip(cols,row):
            if isinstance(v,(bytes,memoryview)) and bytes(v)[:2]==b'GP':
                g=gpkg_blob_to_geom(bytes(v))
                g=transform(lambda x,y,z=None: t.transform(x,y), g)
            else:
                props[c]=v
        feats.append({'type':'Feature','properties':props,'geometry':g.__geo_interface__ if g else None})
    return {'type':'FeatureCollection','features':feats}

if __name__=='__main__':
    path,table,srs,out=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4]
    fc=load(path,table,srs)
    json.dump(fc,open(out,'w'),ensure_ascii=False)
    print(out,len(fc['features']))
