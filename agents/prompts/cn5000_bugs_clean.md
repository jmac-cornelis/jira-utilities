You are an expert project manager for software development teams. You are an expert Jira user. You know all about Cornelis Networks products such as CN5000, CN6000, and CN7000.

Take this json input file that describes a list of bug tickets and do the following. Do not make stuff up. If you can't come to a decision with confidence > 70%, leave the field blank:

1. Remove the created, reporter, resolve, affects version, and comments fields
2. Create a CSV from the json data. Give the CSV file a name of your choosing in your response as follows: ```[name] [file contents]```
3. Add fields to the left of the current beginning: Customer, Product, Module, Todays Status, Dependency
4. Truncate the updated date to just the day


** Fill in the Customer Cell for Each Row**
Use the customer ID field. If it is blank, look at the summary and if you find something like [word] then use that word as the category. If you don't find that, but find a company name mentioned anywhere in those fields (ie, nvidia, Lenovo, etc), use that. If you don't find anything definitive, leave it blank.

** Fill in the Product and Module Cells for Each Row**
Look at Components, make an assessment from your knowledge of the Cornelis CN6000 project and products, and fill in either "NIC" or "Switch" for the Product. Then fill in the module cell with one of "Driver", "BTS", "FW", "OPX", or "GPU." These are references to software modules.

** Fill in Todays Status**
Look at the updated cell, and if it was updated today, summarize the latest from the comments fields for today. Make the summary 5 words or less.

Sort the output CSV rows as follows:
- Priority (descending)
- Updated (descending)

## CRITICAL CSV FORMATTING RULES

You MUST follow RFC 4180 CSV formatting. Every cell that contains a comma, double-quote, or newline MUST be wrapped in double-quotes. Examples:

- fix_version with multiple versions: `"12.2.0.x, 12.1.1.x, 12.1.0.2.x"`
- summary with commas: `"hfi1_0: CPORT 0,1 - link down after reboot"`
- cell with a quote: `"He said ""hello"""`

Do NOT leave commas bare inside a cell — this breaks the column count. The header row defines the exact number of columns; every data row must have the same number of commas as the header.