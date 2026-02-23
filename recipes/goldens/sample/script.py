import json
import sys

def main():
    with open('config/settings.json') as f:
        config = json.load(f)
    
    print(f"Running in {config['environment']} environment for {config['name']}.")
    
    # If the '--generate' flag is passed, write an output file
    if len(sys.argv) > 1 and sys.argv[1] == '--generate':
        with open('output.txt', 'w') as f:
            f.write(f"Generated snapshot output for {config['name']}\n")

if __name__ == '__main__':
    main()