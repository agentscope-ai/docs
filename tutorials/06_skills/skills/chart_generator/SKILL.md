---
name: chart_generator
description: Generate charts and visualizations from data using matplotlib. Supports bar, line, and pie charts with customizable styling.
---

# Chart Generator Skill

You can generate charts from data using Python's matplotlib library.

## Workflow

1. Read or query the data source to get the values you need
2. Write a Python script that uses matplotlib to create the chart
3. Execute the script using the Bash tool

## Chart Types

### Bar Chart
```python
import matplotlib.pyplot as plt

categories = ["A", "B", "C"]
values = [10, 25, 15]

plt.figure(figsize=(8, 5))
plt.bar(categories, values, color="#4CAF50")
plt.title("Revenue by Category")
plt.xlabel("Category")
plt.ylabel("Revenue ($)")
plt.tight_layout()
plt.savefig("output.png", dpi=150)
plt.close()
```

### Line Chart
```python
import matplotlib.pyplot as plt

months = ["Jan", "Feb", "Mar", "Apr"]
values = [100, 150, 130, 180]

plt.figure(figsize=(8, 5))
plt.plot(months, values, marker="o", color="#2196F3", linewidth=2)
plt.title("Monthly Trend")
plt.xlabel("Month")
plt.ylabel("Value")
plt.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig("output.png", dpi=150)
plt.close()
```

### Pie Chart
```python
import matplotlib.pyplot as plt

labels = ["A", "B", "C"]
sizes = [40, 35, 25]

plt.figure(figsize=(7, 7))
plt.pie(sizes, labels=labels, autopct="%1.1f%%", startangle=90)
plt.title("Distribution")
plt.tight_layout()
plt.savefig("output.png", dpi=150)
plt.close()
```

## Style Guidelines

- Always use `plt.tight_layout()` before saving
- Save with `dpi=150` for good quality
- Always call `plt.close()` after saving to free memory
- Use descriptive titles and axis labels
- Default figure size: `(8, 5)` for bar/line, `(7, 7)` for pie
