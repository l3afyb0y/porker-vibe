#!/usr/bin/env python3
"""
Simple test to verify the collaborative framework is working.
"""

import sys
import traceback
from pathlib import Path

def test_imports():
    """Test that all collaborative modules can be imported."""
    try:
        from vibe.collaborative import CollaborativeAgent, TaskManager, ModelCoordinator
        from vibe.collaborative.task_manager import TaskType, ModelRole
        from vibe.collaborative.model_coordinator import ModelConfig
        from vibe.collaborative.collaborative_agent import CollaborativeAgent
        
        print("[OK] All imports successful")
        return True
    except ImportError as e:
        print(f"[FAIL] Import failed: {e}")
        traceback.print_exc()
        return False

def test_task_manager():
    """Test basic TaskManager functionality."""
    try:
        from vibe.collaborative.task_manager import TaskManager, TaskType, ModelRole
        
        # Create a temporary test directory
        test_dir = Path("/tmp/vibe_test")
        test_dir.mkdir(exist_ok=True)
        
        # Initialize task manager
        tm = TaskManager(test_dir)
        
        # Test task creation
        task_id = tm.create_task(TaskType.PLANNING, "Test planning task", priority=1)
        print(f"[OK] Created task: {task_id}")
        
        # Test task assignment
        tm.assign_task(task_id, ModelRole.PLANNER)
        print("[OK] Task assignment successful")
        
        # Test task completion
        tm.complete_task(task_id)
        print("[OK] Task completion successful")
        
        # Test status
        status = tm.get_task_status()
        print(f"[OK] Task status: {status}")
        
        return True
    except Exception as e:
        print(f"[FAIL] TaskManager test failed: {e}")
        traceback.print_exc()
        return False

def test_model_coordinator():
    """Test basic ModelCoordinator functionality."""
    try:
        from vibe.collaborative.model_coordinator import ModelCoordinator
        from vibe.collaborative.task_manager import ModelRole
        
        # Create a temporary test directory
        test_dir = Path("/tmp/vibe_test")
        test_dir.mkdir(exist_ok=True)
        
        # Initialize model coordinator
        mc = ModelCoordinator(test_dir)
        
        # Test configuration
        config = mc.get_project_status()
        print(f"[OK] Model coordinator initialized with config: {config['models_configured']}")
        
        # Test model configuration update
        mc.update_model_config(ModelRole.IMPLEMENTER, "deepseek-coder-v2", "http://localhost:11434/api/generate")
        print("[OK] Model configuration update successful")
        
        return True
    except Exception as e:
        print(f"[FAIL] ModelCoordinator test failed: {e}")
        traceback.print_exc()
        return False

def test_collaborative_agent():
    """Test basic CollaborativeAgent functionality."""
    try:
        from vibe.collaborative import CollaborativeAgent
        from vibe.collaborative.task_manager import TaskType
        
        # Create a temporary test directory
        test_dir = Path("/tmp/vibe_test")
        test_dir.mkdir(exist_ok=True)
        
        # Initialize collaborative agent
        agent = CollaborativeAgent(test_dir)
        
        # Test project status
        status = agent.get_project_status()
        print(f"[OK] Collaborative agent initialized: {status['project_name']}")
        
        # Test adding a custom task
        task_id = agent.add_custom_task(TaskType.DOCUMENTATION, "Test documentation task")
        print(f"[OK] Added custom task: {task_id}")
        
        # Test getting tasks for a model
        from vibe.collaborative.task_manager import ModelRole
        tasks = agent.get_tasks_for_model(ModelRole.IMPLEMENTER)
        print(f"[OK] Tasks for implementer: {tasks['task_count']}")
        
        return True
    except Exception as e:
        print(f"[FAIL] CollaborativeAgent test failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=== Vibe Collaborative Framework Tests ===\n")
    
    tests = [
        ("Import Test", test_imports),
        ("TaskManager Test", test_task_manager),
        ("ModelCoordinator Test", test_model_coordinator),
        ("CollaborativeAgent Test", test_collaborative_agent),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n--- {test_name} ---")
        if test_func():
            passed += 1
            print(f"[OK] {test_name} PASSED")
        else:
            print(f"[FAIL] {test_name} FAILED")
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("[SUCCESS] All tests passed! The collaborative framework is working correctly.")
        return 0
    else:
        print("[FAILURE] Some tests failed. Please check the error messages above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())