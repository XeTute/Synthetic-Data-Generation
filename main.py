#!/usr/bin/env python3
import requests
import json
import ast
import re
import sys
import logging
import time

MAX_LOG_LENGTH = 200  # Maximum number of characters to display in logs

def truncate(text, limit=MAX_LOG_LENGTH):
    """
    Truncate text to the given limit, appending '...' if it exceeds the limit.
    """
    return text if len(text) <= limit else text[:limit] + "..."

# Set up fancy logging (used for non-progress bar messages)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)

def extract_list(response_text):
    """
    Extract a Python list from the response text.
    This function removes common code block markers and then
    attempts to locate the list by finding the first '[' and the last ']'.
    If the resulting list has one multi-line string element,
    it splits that string into individual inputs.
    """
    # Remove common code block markers if present
    cleaned_text = re.sub(r'```(?:python|json)?', '', response_text).strip()
    
    # Find the first '[' and the last ']' to extract the list portion
    start = cleaned_text.find('[')
    end = cleaned_text.rfind(']')
    if start == -1 or end == -1 or end < start:
        raise ValueError("No valid list found in the response.")
    
    list_str = cleaned_text[start:end+1]
    try:
        inputs = ast.literal_eval(list_str)
    except Exception as e:
        raise ValueError("Error parsing list from response.") from e
    
    if not isinstance(inputs, list):
        raise ValueError("Parsed object is not a list.")
    
    # If the list contains a single multi-line string, split it into separate inputs.
    if len(inputs) == 1 and isinstance(inputs[0], str) and "\n" in inputs[0]:
        inputs = [inp.strip() for inp in inputs[0].split('\n') if inp.strip()]
    return inputs

def print_progress_bar(progress, total, start_time, bar_length=40):
    """
    Prints a dynamic progress bar to the console.
    Displays:
    - current progress (e.g., "3/10")
    - a visual bar filled based on percentage completion
    - percentage completed
    - elapsed time and estimated time remaining
    """
    elapsed = time.time() - start_time
    percent = progress / total
    filled_length = int(round(bar_length * percent))
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    # Calculate estimated remaining time
    if progress > 0:
        estimated_total_time = elapsed / progress * total
        time_remaining = estimated_total_time - elapsed
    else:
        time_remaining = 0
    sys.stdout.write(
        f"\r{progress}/{total} | {bar} | {percent*100:6.2f}% | "
        f"{elapsed:6.1f}s elapsed, {time_remaining:6.1f}s remaining"
    )
    sys.stdout.flush()

def main():
    # Ask for completions endpoint and API key
    completions_endpoint = input("Enter the OpenAI-Compatible completions endpoint link (or /v1/chat/completions/-compatible): ").strip()
    api_key = input("Enter your API key: ").strip()
    
    # Set up headers with API key
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # Derive models endpoint if possible
    if "chat/completions" in completions_endpoint:
        base = completions_endpoint.split("chat/completions")[0]
        models_endpoint = base + "models"
    else:
        models_endpoint = input("Enter the models endpoint link: ").strip()
    
    # Fetch available models
    try:
        models_response = requests.get(models_endpoint, headers=headers).json()
        # Try to get a list from "data" or assume the whole response is a list
        models_list = models_response.get("data", models_response)
        if not isinstance(models_list, list):
            raise ValueError("Models response is not a list")
    except Exception as e:
        logging.error(f"Error fetching models: {e}")
        sys.exit(1)
    
    if not models_list:
        logging.error("No models available.")
        sys.exit(1)
    elif len(models_list) == 1:
        selected_model = models_list[0]["id"] if isinstance(models_list[0], dict) and "id" in models_list[0] else models_list[0]
        logging.info(f"Only one model available. Auto-selected: {selected_model}")
    else:
        logging.info("--- Select a Model ---")
        for i, model in enumerate(models_list, start=1):
            model_id = model["id"] if isinstance(model, dict) and "id" in model else model
            logging.info(f"{i}. {model_id}")
        while True:
            try:
                choice = int(input("Enter modelID (number): ").strip())
                if 1 <= choice <= len(models_list):
                    selected_model = (
                        models_list[choice-1]["id"]
                        if isinstance(models_list[choice-1], dict) and "id" in models_list[choice-1]
                        else models_list[choice-1]
                    )
                    break
                else:
                    logging.error("Invalid selection. Try again.")
            except ValueError:
                logging.error("Invalid input. Enter a number.")
        logging.info(f"Selected model: {selected_model}")
    
    # Ask for other parameters
    try:
        n = int(input("How many samples do you need? "))
        if n <= 0:
            logging.error("Number of samples must be positive.")
            sys.exit(1)
    except ValueError:
        logging.error("Invalid input for number of samples.")
        sys.exit(1)

    topics = input("Enter topics (example: \"Versatile questions about Pakistan\", et cetera. Can be both sparse & highly detailed):\n").strip()
    if not topics:
        logging.error("Topics cannot be empty.")
        sys.exit(1)

    # Ask for a system prompt
    system_prompt = input("Enter system prompt (leave empty for none):\n").strip()

    try:
        context_length = int(input("How many k (= *1024) context length does your endpoint support? "))
        context_length *= 1024
    except ValueError:
        logging.error("Invalid input for context length.")
        sys.exit(1)

    outputpath = str(input("Where should the .json file be saved at? (only filename; will append \".json\" to the ending): ")) + str(".json");

    # Define the generate function to wrap API requests.
    def generate(user_input, system_message=""):
        payload = {
            "max_completion_tokens": context_length,
            "model": selected_model,
            "messages": []
        }
        if system_message:
            payload["messages"].append({"role": "system", "content": system_message})
        payload["messages"].append({"role": "user", "content": user_input})
        try:
            response = requests.post(completions_endpoint, json=payload, headers=headers).json()
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logging.error("Error in generate: " + str(e))
            return ""

    all_inputs = []
    chunk_index = 0
    input_start_time = time.time()

    logging.info("Starting to generate unique inputs...")
    # Generate unique inputs with a progress bar
    while True:
        unique_inputs = list(dict.fromkeys(all_inputs))
        if len(unique_inputs) >= n:
            break

        chunk_index += 1
        missing = n - len(unique_inputs)
        # Request either 8 inputs per chunk or only the number still needed.
        chunk_size = 8 if missing >= 8 else missing

        logging.info(f"Requesting chunk {chunk_index} with {chunk_size} new inputs about: {topics}")
        input_prompt = (
            f"Generate exactly {chunk_size} unique inputs about {topics}. \n"
            f"Return ONLY a (Python) list including these inputs, strictly formatted like: [\"input1\", \"input2\", ...]"
        )

        # Retry until we can successfully parse the returned list.
        while True:
            try:
                inputs_text = generate(input_prompt)
                current_inputs = extract_list(inputs_text)
                logging.info(f"Chunk {chunk_index} returned {len(current_inputs)} inputs:")
                for ci in current_inputs:
                    logging.info(f"  - {truncate(ci)}")
                break
            except Exception as e:
                logging.error(f"Parsing failed for chunk {chunk_index}: {e}")
                logging.info("Raw response content:")
                logging.info(truncate(inputs_text) if 'inputs_text' in locals() else "No response received.")
                logging.info("Retrying this chunk...")
                time.sleep(1)

        all_inputs.extend(current_inputs)
        unique_inputs = list(dict.fromkeys(all_inputs))
        # Display progress bar for input generation
        print_progress_bar(len(unique_inputs), n, input_start_time)
        sys.stdout.write("\n")
        sys.stdout.flush()

    # Ensure exactly n unique inputs
    if len(unique_inputs) > n:
        logging.info(f"Received more unique inputs than requested ({len(unique_inputs)} instead of {n}). Using first {n} inputs.")
        unique_inputs = unique_inputs[:n]

    # Generate Q&A pairs (input-output pairs) using each input, with progress bar
    dataset = []
    total = len(unique_inputs)
    logging.info("Starting generation of input-output pairs...")
    qa_start_time = time.time()

    for i, inp in enumerate(unique_inputs, start=1):
        logging.info(f"Generating output for input {i}/{total}: \"{truncate(inp)}\"")
        while True:
            output = generate(inp, system_message=system_prompt)
            if output:
                logging.info(f"Output for input {i}:\n{truncate(output)}")
                break
            else:
                logging.error(f"Error processing input: {truncate(inp)}. Retrying...")
                time.sleep(1)

        dataset.append({
            "instruction": system_prompt,  # store the system prompt if needed
            "input": inp,
            "output": output
        })
        print_progress_bar(i, total, qa_start_time)
        sys.stdout.write("\n")
        sys.stdout.flush()

    # Save the resulting dataset to outputpath
    if dataset:
        try:
            with open(outputpath, 'w') as f:
                json.dump(dataset, f, indent=2)
            logging.info(f"Successfully generated {len(dataset)} samples in {outputpath}.")
        except Exception as e:
            logging.error(f"Error saving file: {e}")
    else:
        logging.error("No valid samples generated.")

if __name__ == '__main__':
    main()
