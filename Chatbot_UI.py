import os
import tkinter as tk
import tkinter.ttk as ttk
os.environ["OPENAI_API_KEY"] = <OPENAI-KEY>
from ChatBot_PoC import agent, prompt
import getpass

# print('Imported UI libraries')
# os.environ["OPENAI_API_KEY"] = getpass.getpass("Enter your OpenAI API key: ")

# Create the UI window
root = tk.Tk()
root.title("Chat with your SQL Database")

# Create the text entry widget
entry = ttk.Entry(root, font=("Arial", 14))
entry.pack(padx=20, pady=20, fill=tk.X)

# Create the button callback
def on_click():
    # Get the query text from the entry widget
    query = entry.get()

    # Run the query using the agent executor
    result = agent.run(prompt.format_prompt(question=query))

    # Display the result in the text widget
    text.delete("1.0", tk.END)
    text.insert(tk.END, result)

# Create the button widget
button = ttk.Button(root, text="Chat", command=on_click)
button.pack(padx=20, pady=20)

# Create the text widget to display the result
text = tk.Text(root, height=10, width=60, font=("Arial", 14))
text.pack(padx=20, pady=20)

# Start the UI event loop
root.mainloop()
