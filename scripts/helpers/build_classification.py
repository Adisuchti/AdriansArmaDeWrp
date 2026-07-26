import os
import glob
import json
from bs4 import BeautifulSoup

def map_category(cat, subcat):
    cat = cat.lower()
    subcat = subcat.lower()
    
    if 'fence' in cat or 'wall' in cat or 'ruin' in cat or 'obstacle' in subcat:
        return 'structures'
    
    if 'lamp' in cat or 'lamp' in subcat:
        return 'lamps'
    
    if 'structure' in cat:
        return 'buildings'
    
    if 'equipment' in cat or 'weapon' in cat or 'supplies' in cat or 'furniture' in cat or 'sign' in cat or 'wreck' in cat or 'thing' in cat:
        return 'clutter'
    
    return 'clutter'

def main():
    folder = os.path.join(os.path.dirname(__file__), '..', 'categorization')
    files = glob.glob(os.path.join(folder, '*.html'))
    
    classification = {}
    count = 0
    
    for f in files:
        print(f"Parsing {os.path.basename(f)}...")
        with open(f, 'r', encoding='utf-8') as html_file:
            soup = BeautifulSoup(html_file, 'html.parser')
            tables = soup.find_all('table')
            for t in tables:
                headers = [th.text.strip() for th in t.find_all('th')]
                if 'Class Name' in headers and 'Category' in headers:
                    class_idx = headers.index('Class Name')
                    cat_idx = headers.index('Category')
                    subcat_idx = headers.index('Subcategory') if 'Subcategory' in headers else -1
                    
                    rows = t.find_all('tr')[1:] # skip header row
                    for r in rows:
                        cols = [td.text.strip() for td in r.find_all('td')]
                        if len(cols) > max(class_idx, cat_idx):
                            class_name = cols[class_idx].lower()
                            cat = cols[cat_idx]
                            subcat = cols[subcat_idx] if subcat_idx != -1 and len(cols) > subcat_idx else ''
                            
                            mapped_layer = map_category(cat, subcat)
                            classification[class_name] = mapped_layer
                            count += 1
                            
    out_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web', 'classification.json'))
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(classification, f, indent=4)
        
    print(f"Successfully mapped {count} items into {out_path}")

if __name__ == '__main__':
    main()
