import argparse
import sys
import os

# Adjust path to import detection modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "detection")))

from detection.config import settings
from detection.main import run_pipeline

def main():
    parser = argparse.ArgumentParser(description="RetailIQ CCTV Analytics Pipeline Runner")
    parser.add_argument("--cam", type=int, default=1, choices=[1, 2, 3, 4, 5],
                        help="Camera number to process (1 to 5)")
    parser.add_argument("--display", action="store_true",
                        help="Show debug window output (requires GUI/desktop environment)")
    
    args = parser.parse_args()
    
    # Store ID ST1008
    settings.store_id = "550e8400-e29b-41d4-a716-446655440000"
    
    # Map camera details
    settings.camera_id = f"cam0{args.cam}"
    settings.video_source = os.path.abspath(os.path.join(os.path.dirname(__file__), "CCTV Footage", f"CAM {args.cam}.mp4"))
    settings.zone_config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "detection", "store_layout.json"))
    settings.debug_display = args.display
    
    # Set backend URL
    settings.backend_url = "http://localhost:8000"
    
    print("=" * 60)
    print(f"Starting RetailIQ Pipeline")
    print(f"Store ID:  {settings.store_id}")
    print(f"Camera:    {settings.camera_id}")
    print(f"Source:    {settings.video_source}")
    print(f"Backend:   {settings.backend_url}")
    print(f"Display:   {settings.debug_display}")
    print("=" * 60)
    
    if not os.path.exists(settings.video_source):
        print(f"Error: Video file not found: {settings.video_source}")
        sys.exit(1)
        
    try:
        run_pipeline(settings)
    except KeyboardInterrupt:
        print("\nPipeline stopped by user request.")
    except Exception as e:
        print(f"\nExecution error: {e}")

if __name__ == "__main__":
    main()
