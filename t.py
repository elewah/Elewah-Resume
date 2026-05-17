
from pathlib import Path
from ats_resume_checker.agent import run_improvement_agent

tex = Path("main.tex").read_bytes()
pdf = Path("main.pdf").read_bytes()

result = run_improvement_agent(
    tex_bytes=tex,
    pdf_bytes=pdf,
    max_iterations=3,
    model="claude-sonnet-4-6",
)

print(f"Score: {result.initial_score} → {result.final_score}")
print(f"\nAgent reasoning ({len(result.progress_messages)} messages):")
for msg in result.progress_messages:
    print(msg)

# Save the improved .tex
if result.final_score > result.initial_score:
    Path("main_improved.tex").write_text(result.improved_tex)
    print("\nSaved improved resume to main_improved.tex")


from pathlib import Path
from ats_resume_checker.agent import run_improvement_agent

result = run_improvement_agent(
    tex_bytes=Path("main.tex").read_bytes(),
    pdf_bytes=Path("main.pdf").read_bytes(),
    max_iterations=3,
    model="claude-sonnet-4-6",
    api_key="sk-ant-...",          # Anthropic API key from console.anthropic.com
)

print(f"Score: {result.initial_score} → {result.final_score}")
if result.final_score > result.initial_score:
    Path("main_improved.tex").write_text(result.improved_tex)
    print("Saved to main_improved.tex")

