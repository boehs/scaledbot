import os
import pywikibot
import csv
import mwparserfromhell
from difflib import get_close_matches
import json
from src.shared import allow_bots

# CONFIG
CSV_FILE = "census_latest.csv"  # format: geoid,place,population
CENSUS_YEAR = 2020  # adjust to latest census year
CENSUS_REF = "<ref>{{Cite web |date=2020-04-01 |title=2020 Census Decennial Demographic and Housing Characteristics: Population by Place (Table P1) |url=https://data.census.gov/table/DECENNIALDHC2020.P1?t=Populations+and+People&g=010XX00US$0600000,$1600000&d=DEC+Demographic+and+Housing+Characteristics |archive-url=https://archive.is/XepMr |archive-date=2025-09-24 |access-date=2025-09-24 |website=Census Bureau Data}}</ref>"
CENSUS_EST_REF = "<ref>{{cite web |title=Annual Estimates of the Resident Population |url=https://www.census.gov/data/tables/time-series/demo/popest/2020s-total-cities-and-towns.html |publisher=United States Census Bureau |access-date=2025-09-16}}</ref>"
EST_YEAR = 2024
BATCH = "1"

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
        # if the key goes like "X city, Y county, Z state", remove "Y county"
        parts = key.split(",")
        if len(parts) == 3 and "county" in parts[1].lower():
            key = f"{parts[0].strip()}, {parts[2].strip()}"
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

# progress json
with open(os.path.join(os.path.dirname(__file__), "progress.json"), "r") as f:
    progress = json.load(f)

# Connect to enwiki
site = pywikibot.Site("en", "wikipedia")
site.login()
print("As user:", site.user())

# Get pages that transclude the templates
templates = ["Template:US Census population", "Template:Infobox settlement"]
pages = set()
'''
for t in templates:
    tpl = pywikibot.Page(site, t)
    for trans in tpl.getReferences(only_template_inclusion=True, follow_redirects=False):
        # check if progress has this page, and if batch 1 exists
        if str(trans.title()) in progress and BATCH in progress[str(trans.title())] and len(progress[str(trans.title())][BATCH]) > 0:
            print(f"    Skipping {trans.title()}: already processed")
        else:
            pages.add(trans)
            # add page to progress
            if str(trans.title()) not in progress:
                progress[str(trans.title())] = {}
                progress[str(trans.title())][BATCH] = {}
'''
# add to pages using Category:Pages using US Census population needing update
cat = pywikibot.Category(site, "Category:Pages using US Census population needing update")
for page in cat.articles():
    if str(page.title()) in progress and BATCH in progress[str(page.title())] and len(progress[str(page.title())][BATCH]) > 0:
        print(f"    Skipping {page.title()}: already processed")
    else:
        pages.add(page)
        # add page to progress
        if str(page.title()) not in progress:
            progress[str(page.title())] = {}
            progress[str(page.title())][BATCH] = {}
# Helper: normalize title
def normalize_title(title):
    parts = [p.strip() for p in title.split(",")]
    if len(parts) == 3:
        return f"{parts[0]}, {parts[2]}"
    return title.strip()

def form_edits_summary(tasks: list[str]):
    str = "Update census info: " + tasks[0]
    # group by prefix before colon, such that it looks like "ucp: (+latest res, -old est); ibox: (+latest res)"
    task_dict = {}
    for task in tasks[1:]:
        prefix, action = task.split(": ")
        if prefix not in task_dict:
            task_dict[prefix] = []
        task_dict[prefix].append(action)
    for prefix, actions in task_dict.items():
        str += f"; {prefix}: ({', '.join(actions)})"
    return str

def update_progress(page_title, data):
    progress[str(page_title)][BATCH] = data
    with open(os.path.join(os.path.dirname(__file__), "progress.json"), "w") as f:
        json.dump(progress, f, indent=2)

# Main loop
total = 0
for page in pages:
    title = str(page.title())
    found = False
    norm_title = normalize_title(title)
    text = None
    if norm_title not in census_data:
        # try searching with "city", "town", "village", "township"
        # Split on comma and try adding suffix to the first part
        parts = norm_title.split(", ")
        canidates = []
        for suffix in [" city", " town", " village", " township", " CDP"]:
            test_name = parts[0] + suffix
            if len(parts) > 1:
                test_name += ", " + ", ".join(parts[1:])
            if test_name in census_data:
                canidates.append(test_name)
        if len(canidates) == 1:
            norm_title = canidates[0]
            found = True
        elif len(canidates) > 1:
            print(f"   Multiple candidates found: {', '.join(canidates)}")
            try:
                text = page.get()
            except Exception as e:
                pass
            if text:
                wikicode = mwparserfromhell.parse(text)
                # attempt to get FIPS code from text by checking if infobox settlement has string "FIPS code" in "blank_name" or "blank1_name" and then use "blank_info" or "blank1_info"
                for template in wikicode.filter_templates():
                    name = template.name.strip().lower()
                    fips_code = None
                    if name == "infobox settlement" and len(wikicode.filter_templates(matches=lambda t: t.name.strip().lower() == "infobox settlement")) == 1:
                        if template.has("blank_name") and "FIPS code" in template.get("blank_name").value:
                            fips_code = template.get("blank_info").value.strip().replace("-", "")
                            print(f"   Found FIPS code {fips_code} for {title}")
                        elif template.has("blank1_name") and "FIPS code" in template.get("blank1_name").value:
                            fips_code = template.get("blank1_info").value.strip().replace("-", "")
                            print(f"   Found FIPS code {fips_code} for {title}")
                    if fips_code is not None:
                        for canidate in canidates:
                            if census_data[canidate]["geoid"].endswith(fips_code):
                                norm_title = canidate
                                found = True
                                print(f"   Matched {title} to {norm_title} via FIPS code")
                                break

        # Try fuzzy matching for minor discrepancies
        if not found:
            best_match = get_close_matches(norm_title, census_data.keys(), n=1, cutoff=0.95)
            if best_match:
                norm_title = best_match[0]
                found = True
        if not found:
            print(f"Skipping {title}: not found in census data")
            update_progress(page.title(), {"skipped": "not found in census data"})
            continue
    print(f"Processing {title} as {norm_title}")

    pop = int(census_data[norm_title]["population"])
    est = int(census_data[norm_title].get("est", None))

    if text is None:
        try:
            text = page.get()
        except Exception as e:
            print(f"Skipping {title}: {e}")
            update_progress(page.title(), {"error": str(e)})
            continue

    # ensure page contains "US Census population" or "United States"
    if not ("us census population" in text.lower() or "united states" in text.lower()):
        print(f"     Skipping {title}: does not appear to be a US location")
        update_progress(page.title(), {"skipped": "not a US location"})
        continue

    wikicode = mwparserfromhell.parse(text)
    if not allow_bots(wikicode,"Scaledbot"):
        print(f"Skipping {page.title()}: bots not allowed")
        update_progress(page.title(), {"skipped": "bots not allowed"})
        continue

    modified = False

    tasks = [f"Matched {norm_title}"]

    for template in wikicode.filter_templates():
        name = template.name.strip().lower()

        if name == "us census population" and len(wikicode.filter_templates(matches=lambda t: t.name.strip().lower() == "us census population")) == 1:
            # check if it has 2020 and if it is sourced
            if template.has(CENSUS_YEAR) and int(template.get(CENSUS_YEAR).value.strip().replace(',', '')) != pop and template.has(f"{CENSUS_YEAR}n"):
                print(f"    {CENSUS_YEAR} population differs and is sourced")
            elif template.has(CENSUS_YEAR) and int(template.get(CENSUS_YEAR).value.strip().replace(',', '')) == pop:
                print(f"    {CENSUS_YEAR} population is up to date")
            else:
                template.add(CENSUS_YEAR, pop)
                template.add(f"{CENSUS_YEAR}n", CENSUS_REF)
                modified = True
                tasks.append("ucp: +latest res")

            # ESTIMATES #

            # if the census is newer than estyear, remove estyear and est and estref
            if template.has("estyear"):
                estyear = template.get("estyear").value.strip().replace(',','')
                if estyear.isdigit() and int(estyear) <= CENSUS_YEAR:
                    print(f"    Removing outdated estimates for {estyear}")
                    for param in ["estyear", "estimate", "estref"]:
                        if template.has(param):
                            template.remove(param)
                    modified = True
                    tasks.append("ucp: -old est")

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
                    try:
                        tasks.remove("ucp: -old est")
                        tasks.remove("ucp: -est w no estyear")
                    except ValueError:
                        pass
                    tasks.append("ucp: +lastest est")

        if name == "infobox settlement" and len(wikicode.filter_templates(matches=lambda t: t.name.strip().lower() == "infobox settlement")) == 1:
            # similar to before now. check if population_as_of is older than census year
            current_year = None
            if template.has("population_as_of"):
                if not CENSUS_YEAR in template.get("population_as_of").value and template.has("population_total"):
                    # find a number in population_as_of
                    year_str = template.get("population_as_of").value.strip()
                    for part in year_str.split():
                        if part.isdigit():
                            current_year = int(part)
                            break
                    if current_year is not None and current_year > CENSUS_YEAR:
                        print(f".   Skipping {title}: population_as_of is newer than census year")
                    else:
                        # If we get here, population_as_of is older than census year
                        print(f".   Updating population to {CENSUS_YEAR} census")
                        template.add("population_as_of", f"[[{CENSUS_YEAR} United States Census|{CENSUS_YEAR}]]")
                        template.add("population_total", f"{pop:,}")
                        modified = True
                        tasks.append("ibox: +latest res")
            if current_year is None or (current_year is not None and current_year < CENSUS_YEAR):
                current_year = CENSUS_YEAR
            # ESTIMATES #
            current_estyear: None | int = None
            if template.has("population_est") and template.has("population_est_as_of"):
                estyear_str = template.get("population_est_as_of").value.strip()
                for part in estyear_str.split():
                    if part.isdigit():
                        current_estyear = int(part)
                        break
                if current_estyear is not None and current_estyear < current_year:
                    print(f".   Removing outdated estimates for {current_estyear}")
                    for param in ["population_est", "population_est_as_of", "population_est_footnotes"]:
                        if template.has(param):
                            template.remove(param)
                    modified = True
                    tasks.append("ibox: -old est")
            if est and (current_estyear is None or (current_estyear is not None and current_estyear < EST_YEAR)):
                template.add("pop_est_as_of", EST_YEAR)
                template.add("population_est", f"{est:,}")
                modified = True
                tasks.append("ibox: +latest est")
                try:
                    tasks.remove("ibox: -old est")
                except ValueError:
                    pass

    if modified:
        page.text = str(wikicode)
        print(f"Modified text for {title}.")
        try:
            page.save(summary=form_edits_summary(tasks), bot=True)
            total += 1
        except Exception as e:
            print(f"Failed to save {title}: {e}")
            update_progress(page.title(), {"error": str(e)})
        finally:
            print("Saved with summary:", form_edits_summary(tasks) + " n." + str(total))
            update_progress(page.title(), {"tasks": tasks, "census_name": norm_title})
    else:
        update_progress(page.title(), {"skipped": "no changes needed"})

print(f"Done. Updated {total} pages.")
