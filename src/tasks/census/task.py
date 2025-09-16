import os
import pywikibot
import csv
import mwparserfromhell
from difflib import get_close_matches
import subprocess
from src.shared import allow_bots

# CONFIG
CSV_FILE = "census_latest.csv"  # format: geoid,place,population
CENSUS_YEAR = 2020  # adjust to latest census year
CENSUS_REF = "<ref>{{cite web |title=Decennial Census of Population and Housing |url=https://www.census.gov/programs-surveys/decennial-census.html |publisher=United States Census Bureau |access-date=2025-09-16}}</ref>"
CENSUS_EST_REF = "<ref>{{cite web |title=Annual Estimates of the Resident Population |url=https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-cities-and-towns.html |publisher=United States Census Bureau |access-date=2025-09-16}}</ref>"
EST_YEAR = 2024

# Load census data into dict
census_data = {}
with open(os.path.join(os.path.dirname(__file__), CSV_FILE), newline='', encoding='utf-8-sig') as f:
    reader = csv.reader(f)
    headers = next(reader)  # first row
    headers = [h.strip().strip('"') for h in headers]  # clean quotes
    reader = csv.DictReader(f, fieldnames=headers)
    next(reader)  # skip second metadata row
    for row in reader:
        key = row["NAME"].strip()
        key = key.replace(" CDP", "")
        census_data[key] = {
            "geoid": row["GEO_ID"],
            "population": row["P1_001N"]
        }
with open(os.path.join(os.path.dirname(__file__), "census_est.csv"), newline='', encoding='utf-8-sig') as f:
    # try to find the census_data[key] and update population if found
    reader = csv.reader(f)
    headers = next(reader)  # first row
    headers = [h.strip().strip('"') for h in headers]  # clean quotes
    reader = csv.DictReader(f, fieldnames=headers)
    for row in reader:
        key = row["NAME"].strip()
        key = key.replace(" CBT", "")
        if key in census_data:
            census_data[key]["est"] = row["P1_001N"]

# Connect to enwiki
site = pywikibot.Site("en", "wikipedia")
#site.login()

# Get pages that transclude the templates
templates = ["Template:US Census population", "Template:Infobox settlement"]
pages = set()
'''
for t in templates:
    tpl = pywikibot.Page(site, t)
    for trans in tpl.getReferences(only_template_inclusion=True, follow_redirects=False):
        pages.add(trans)
'''
# add to pages using Category:Pages using US Census population needing update
cat = pywikibot.Category(site, "Category:Pages using US Census population needing update")
for page in cat.articles():
    pages.add(page)

# Helper: normalize title
def normalize_title(title):
    parts = [p.strip() for p in title.split(",")]
    if len(parts) == 3:
        return f"{parts[0]}, {parts[2]}"
    return title.strip()

# Main loop
total = 0
for page in pages:
    title = str(page.title())
    found = False
    norm_title = normalize_title(title)
    if norm_title not in census_data:
        # try searching with "city", "town", "village", "township"
        # Split on comma and try adding suffix to the first part
        parts = norm_title.split(", ")
        for suffix in [" city", " town", " village", " township", " CDP"]:
            test_name = parts[0] + suffix
            if len(parts) > 1:
                test_name += ", " + ", ".join(parts[1:])
            if test_name in census_data:
                norm_title = test_name
                found = True
                break
        # Try fuzzy matching for minor discrepancies
        if not found:
            best_match = get_close_matches(norm_title, census_data.keys(), n=1, cutoff=0.95)
            if best_match:
                norm_title = best_match[0]
                found = True
        if not found:
            print(f"Skipping {title}: not found in census data")
            continue
    print(f"Processing {title} as {norm_title}")

    pop = int(census_data[norm_title]["population"])
    est = int(census_data[norm_title].get("est", None))

    try:
        text = page.get()
    except Exception as e:
        print(f"Skipping {title}: {e}")
        continue

    # ensure page contains "US Census population" or "United States"
    if not ("us census population" in text.lower() or "united states" in text.lower()):
        print(f"     Skipping {title}: does not appear to be a US location")
        continue

    wikicode = mwparserfromhell.parse(text)
    if not allow_bots(wikicode,"Scaledbot"):
        print(f"Skipping {page.title()}: bots not allowed")
        continue

    modified = False

    for template in wikicode.filter_templates():
        name = template.name.strip().lower()

        if name == "us census population" and len(wikicode.filter_templates(matches=lambda t: t.name.strip().lower() == "us census population")) == 1:
            # check if it has 2020
            if template.has(CENSUS_YEAR):
                # if there is a discrepancy and it is sourced we let it slide
                if template.get(CENSUS_YEAR).value.strip() != pop and template.has(f"{CENSUS_YEAR}n"):
                    print(f"    {CENSUS_YEAR} population differs and is sourced")
                    continue
            template.add(CENSUS_YEAR, pop)
            template.add(f"{CENSUS_YEAR}n", CENSUS_REF)
            modified = True

            # if the census is newer than estyear, remove estyear and est and estref
            if template.has("estyear"):
                estyear = template.get("estyear").value.strip().replace(',','')
                if estyear.isdigit() and int(estyear) <= CENSUS_YEAR:
                    print(f"    Removing outdated estimates for {estyear}")
                    for param in ["estyear", "estimate", "estref"]:
                        if template.has(param):
                            template.remove(param)

            if est:
                skip = False
                # if there is already estimate for EST_YEAR or if the existing estyear is newer than EST_YEAR, skip
                if template.has("estyear"):
                    existing_estyear = template.get("estyear").value.strip().replace(',','')
                    if existing_estyear.isdigit() and int(existing_estyear) >= EST_YEAR:
                        print(f"    Skipping estimate for {EST_YEAR}: existing estyear is newer or same")
                        skip = True
                if not skip:
                    print(f"    Adding estimate for {EST_YEAR}")
                    template.add("estyear", EST_YEAR)
                    template.add("estimate", est)
                    template.add("estref", CENSUS_EST_REF)
                    modified = True

        # ensure there is only one of each template
        if name == "infobox settlement" and len(wikicode.filter_templates(matches=lambda t: t.name.strip().lower() == "infobox settlement")) == 1:
            # similar to before now. check if population_as_of is older than census year
            if template.has("population_as_of"):
                if not CENSUS_YEAR in template.get("population_as_of").value and template.has("population_total"):
                    # find a number in population_as_of
                    year_str = template.get("population_as_of").value.strip()
                    year = None
                    for part in year_str.split():
                        if part.isdigit():
                            year = int(part)
                            break
                    if year is not None and year > CENSUS_YEAR:
                        print(f".   Skipping {title}: population_as_of is newer than census year")
                        continue
                    # If we get here, population_as_of is older than census year
                    print(f".   Updating population to {CENSUS_YEAR} census")
                    template.add("population_as_of", f"[[{CENSUS_YEAR} United States Census|{CENSUS_YEAR}]]")
                    template.add("population_total", f"{pop:,}")
                    modified = True
                if template.has("population_est") and template.has("population_est_as_of"):
                    estyear_str = template.get("population_est_as_of").value.strip()
                    estyear = None
                    for part in estyear_str.split():
                        if part.isdigit():
                            estyear = int(part)
                            break
                    if estyear is not None and estyear <= CENSUS_YEAR:
                        print(f".   Removing outdated estimates for {estyear}")
                        for param in ["population_est", "population_est_as_of", "population_est_footnotes"]:
                            if template.has(param):
                                template.remove(param)
                        modified = True
                if est:
                    template.add("pop_est_as_of", EST_YEAR)
                    template.add("population_est", f"{est:,}")
                    modified = True


    if modified:
        page.text = str(wikicode)
        subprocess.run("pbcopy", text=True, input=str(wikicode))
        print(f"Modified text for {title}.")
        '''
        try:
            page.save(summary=f"Update census info")
            total += 1
        except Exception as e:
            print(f"Failed to save {title}: {e}")
        '''

print(f"Done. Updated {total} pages.")
