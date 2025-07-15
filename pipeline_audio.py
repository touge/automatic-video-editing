# -*- coding: utf-8 -*-
"""
main.py

The main pipeline for the audio search toolkit.
This script demonstrates how to use the modularized core components
to perform a full workflow:
1. Preprocess (Transcribe) an audio file.
2. Align a text file with the transcription.
3. Search for queries within the aligned data.
4. Generate an SRT file from the search results.
"""
import logging
import os
import json
import pickle
import argparse

from src.core.model_loader import ModelLoader
from src.core.audio import AudioProcessor
from src.core.text import TextProcessor
from src.core.search import Searcher
from src.config_loader import Config

def setup_logging(config: Config):
    """
    Configures the root logger for consistent output that works well with tqdm.
    """
    log_level = config.get('logging.level', 'INFO').upper()
    log_format = config.get('logging.format', '%(asctime)s - %(levelname)s - %(message)s')
    
    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()
        
    # Create a handler that writes to the console
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    
    # Create a formatter and add it to the handler
    formatter = logging.Formatter(log_format)
    handler.setFormatter(formatter)
    
    # Add the handler to the logger
    logger.addHandler(handler)

def run_pipeline(config: Config, audio_path: str, text_path: str, queries: list, output_dir: str, verbose: bool = False):
    """
    Executes the full audio search and alignment pipeline.

    Args:
        config (Config): The application configuration object.
        audio_path (str): Path to the input audio file.
        text_path (str): Path to the input text file for alignment.
        queries (list): A list of strings to search for.
        output_dir (str): Directory to save all intermediate and final files.
        verbose (bool): If True, enables detailed logging for each match.
    """
    logging.info("Starting audio search pipeline...")
    os.makedirs(output_dir, exist_ok=True)

    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    
    # --- File Paths ---
    whisper_json_path = os.path.join(output_dir, f"{base_name}.whisper.json")
    aligned_pkl_path = os.path.join(output_dir, f"{base_name}.aligned.pkl")
    search_results_path = os.path.join(output_dir, f"{base_name}.search.json")
    final_srt_path = os.path.join(output_dir, f"{base_name}.srt")

    try:
        # --- 1. Initialize Core Components ---
        # The singleton ModelLoader ensures models are loaded only once.
        # This is now done inside the pipeline, avoiding pre-loading.
        logging.info("Initializing core components...")
        model_loader = ModelLoader(config) # Pass the config object
        audio_processor = AudioProcessor(model_loader)
        text_processor = TextProcessor(model_loader)
        searcher = Searcher(model_loader, text_processor)
        logging.info("Core components initialized.")

        # --- 2. Preprocessing (Transcription) ---
        if os.path.exists(whisper_json_path):
            logging.info(f"Found existing Whisper cache: {whisper_json_path}")
            with open(whisper_json_path, 'r', encoding='utf-8') as f:
                whisper_segments = json.load(f)
        else:
            logging.info(f"Running transcription for {audio_path}...")
            _, whisper_segments, _ = audio_processor.transcribe(audio_path)
            if not whisper_segments:
                raise RuntimeError("Transcription failed.")
            with open(whisper_json_path, 'w', encoding='utf-8') as f:
                json.dump(whisper_segments, f, ensure_ascii=False, indent=4)
            logging.info(f"Transcription saved to {whisper_json_path}")

        # --- 3. Alignment ---
        if os.path.exists(aligned_pkl_path):
            logging.info(f"Found existing alignment cache: {aligned_pkl_path}")
            with open(aligned_pkl_path, 'rb') as f:
                aligned_data = pickle.load(f)['segments_info']
        else:
            logging.info(f"Running alignment for {text_path}...")
            with open(text_path, 'r', encoding='utf-8') as f:
                target_lines = [line.strip() for line in f if line.strip()]
            
            all_whisper_words = [word for segment in whisper_segments for word in segment.get('words', [])]
            aligned_data, _ = searcher.linear_align(target_lines, all_whisper_words)
            
            # Save alignment cache
            with open(aligned_pkl_path, 'wb') as f:
                pickle.dump({"segments_info": aligned_data}, f)
            logging.info(f"Alignment data saved to {aligned_pkl_path}")

        # --- 4. Search ---
        logging.info(f"Searching for {len(queries)} queries...")
        all_search_results = []
        for query in queries:
            best_match = searcher.search(query, aligned_data)
            if best_match:
                all_search_results.append(best_match)
                if verbose:
                    logging.info(f"Found match for '{query}': {best_match['text']} @ {best_match['start']:.2f}s")
        
        with open(search_results_path, 'w', encoding='utf-8') as f:
            json.dump(all_search_results, f, ensure_ascii=False, indent=4)
        logging.info(f"Search results saved to {search_results_path}")

        # --- 5. Generate SRT ---
        logging.info("Generating SRT file...")
        unique_entries = set()
        processed_results = []
        for entry in all_search_results:
            unique_key = (entry['text'], entry['start'], entry['end'])
            if unique_key not in unique_entries:
                unique_entries.add(unique_key)
                processed_results.append(entry)
        
        processed_results.sort(key=lambda x: x['start'])

        with open(final_srt_path, 'w', encoding='utf-8') as f:
            for i, entry in enumerate(processed_results):
                start_time = TextProcessor.format_time(entry['start'])
                end_time = TextProcessor.format_time(entry['end'])
                f.write(f"{i + 1}\n")
                f.write(f"{start_time} --> {end_time}\n")
                f.write(f"{entry['text']}\n\n")
        logging.info(f"Final SRT file generated at: {final_srt_path}")

    except Exception as e:
        logging.critical(f"Pipeline failed: {e}", exc_info=True)

    logging.info("Pipeline finished.")


if __name__ == '__main__':
    # Load config first, but it's a very fast operation.
    # Models will NOT be loaded here.
    try:
        config = Config()
    except Exception as e:
        logging.critical(f"Failed to load configuration. Please check config.yaml. Error: {e}")
        exit(1)

    # Setup logging based on the loaded config
    setup_logging(config)

    parser = argparse.ArgumentParser(
        description="Run the full audio search pipeline.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-a", "--audio",
        required=True,
        help="Path to the input audio file (e.g., assets/s2.wav)."
    )
    parser.add_argument(
        "-t", "--text-path",
        required=True,
        help="Path to the text file. This file is used for alignment and as the default source for queries."
    )
    parser.add_argument(
        "-q", "--query",
        help='Optional: A single query or comma-separated list of queries (e.g., "query1,query two").\nIf provided, this will override using the --text-path file for queries.'
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=config.get('defaults.output_dir', 'output/pipeline_run'),
        help="Directory to save all output files. Overrides config file setting."
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output, including details for each search match."
    )
    
    args = parser.parse_args()

    # Determine the source of queries based on priority
    query_list = []
    if args.query:
        logging.info(f"Using queries from command line argument: --query")
        query_list = [q.strip() for q in args.query.split(',') if q.strip()]
    else:
        logging.info(f"Using text file for queries: --text-path")
        if os.path.exists(args.text_path):
            with open(args.text_path, 'r', encoding='utf-8') as f:
                query_list = [line.strip() for line in f if line.strip()]
        else:
            # This case is also caught by the main validation below, but good to have
            logging.error(f"Error: Text file not found at '{args.text_path}'")
            query_list = []

    # Main validation
    if not query_list:
        logging.error("Error: No queries to process. Provide them via --query or ensure the --text-path file is not empty.")
    elif not os.path.exists(args.audio) or not os.path.exists(args.text_path):
        logging.error(f"Error: Make sure audio ('{args.audio}') and text ('{args.text_path}') files exist.")
    else:
        # Only now, when we are sure we need to run the full task,
        # do we call the main pipeline function.
        run_pipeline(
            config=config,
            audio_path=args.audio,
            text_path=args.text_path, # This is always used for alignment
            queries=query_list,      # This is the determined list of queries
            output_dir=args.output_dir,
            verbose=args.verbose     # Pass the verbose flag
        )
