import React, { useState, useEffect } from 'react';
import { apiClient, User, ConnectionStatus, Instruction, Task } from '../lib/api';
import Chat from '../components/Chat';
import ConnectionBadges from '../components/ConnectionBadges';

const Dashboard: React.FC = () => {
  const [user, setUser] = useState<User | null>(null);
  const [connections, setConnections] = useState<ConnectionStatus | null>(null);
  const [instructions, setInstructions] = useState<Instruction[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showInstructions, setShowInstructions] = useState(false);
  const [newInstruction, setNewInstruction] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [showSearchResults, setShowSearchResults] = useState(false);

  useEffect(() => {
    loadUserData();
  }, []);

  const loadUserData = async () => {
    try {
      const [userData, connectionsData, instructionsData, tasksData] = await Promise.all([
        apiClient.getCurrentUser(),
        apiClient.getConnections(),
        apiClient.getInstructions(),
        apiClient.getTasks(),
      ]);

      setUser(userData);
      setConnections(connectionsData);
      setInstructions(instructionsData);
      setTasks(tasksData);
    } catch (error) {
      console.error('Failed to load user data:', error);
      // User not authenticated, will show login
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleConnect = () => {
    apiClient.googleLogin();
  };

  const handleHubSpotConnect = () => {
    apiClient.hubspotLogin();
  };

  const handleInitialSync = async () => {
    try {
      setIsLoading(true);
      await apiClient.ingestInitialData();
      alert('Initial sync started! Your Gmail and HubSpot data is being ingested in the background.');
    } catch (error) {
      console.error('Failed to start initial sync:', error);
      alert('Failed to start initial sync. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateInstruction = async () => {
    if (!newInstruction.trim()) return;

    try {
      const instruction = await apiClient.createInstruction(newInstruction);
      setInstructions(prev => [...prev, instruction]);
      setNewInstruction('');
    } catch (error) {
      console.error('Failed to create instruction:', error);
    }
  };

  const handleToggleInstruction = async (id: string, is_active: boolean) => {
    try {
      await apiClient.updateInstruction(id, !is_active);
      setInstructions(prev =>
        prev.map(inst =>
          inst.id === id ? { ...inst, is_active: !is_active } : inst
        )
      );
    } catch (error) {
      console.error('Failed to update instruction:', error);
    }
  };

  const handleSearchResults = (results: any[]) => {
    setSearchResults(results);
    setShowSearchResults(true);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="animate-spin rounded-full h-32 w-32 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100">
        <div className="container mx-auto px-4 py-16">
          <div className="max-w-4xl mx-auto text-center">
            {/* Header */}
            <div className="mb-12">
              <h1 className="text-5xl font-bold text-gray-900 mb-4">
                Financial Advisor AI Agent
              </h1>
              <p className="text-xl text-gray-600 mb-8">
                Your intelligent assistant for managing financial tasks and client relationships
              </p>
            </div>

            {/* Main CTA */}
            <div className="bg-white rounded-2xl shadow-xl p-8 mb-12">
              <h2 className="text-2xl font-semibold text-gray-800 mb-4">
                Get Started
              </h2>
              <p className="text-gray-600 mb-6">
                Sign in with Google to access your personalized dashboard, manage instructions, view tasks, and interact with your AI assistant.
              </p>
              <button
                onClick={handleGoogleConnect}
                className="inline-block bg-blue-600 text-white px-8 py-4 rounded-lg text-lg font-semibold hover:bg-blue-700 transition-colors shadow-lg hover:shadow-xl"
              >
                Sign in with Google
              </button>
            </div>

            {/* Features Grid */}
            <div className="grid md:grid-cols-3 gap-8">
              <div className="bg-white rounded-xl p-6 shadow-lg">
                <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center mx-auto mb-4">
                  <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-gray-800 mb-2">AI Chat Assistant</h3>
                <p className="text-gray-600 text-sm">
                  Interact with your AI assistant to get help with financial tasks and client management.
                </p>
              </div>

              <div className="bg-white rounded-xl p-6 shadow-lg">
                <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center mx-auto mb-4">
                  <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-gray-800 mb-2">Task Management</h3>
                <p className="text-gray-600 text-sm">
                  Track and manage ongoing tasks with real-time status updates and progress monitoring.
                </p>
              </div>

              <div className="bg-white rounded-xl p-6 shadow-lg">
                <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center mx-auto mb-4">
                  <svg className="w-6 h-6 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <h3 className="text-lg font-semibold text-gray-800 mb-2">Smart Integrations</h3>
                <p className="text-gray-600 text-sm">
                  Connect with Gmail, Google Calendar, and HubSpot for seamless data synchronization.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Financial Advisor AI Agent</h1>
              <p className="text-sm text-gray-600 mt-1">Welcome back, {user.name}</p>
            </div>
            <div className="flex items-center space-x-4">
              {connections && (connections.gmail || connections.hubspot) && (
                <button
                  onClick={handleInitialSync}
                  disabled={isLoading}
                  className="px-6 py-3 text-sm bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl hover:from-blue-700 hover:to-purple-700 transition-colors font-medium shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  🔄 {isLoading ? 'Syncing...' : 'Initial Sync'}
                </button>
              )}
              <button
                onClick={() => setShowInstructions(!showInstructions)}
                className="px-6 py-3 text-sm bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors font-medium shadow-sm"
              >
                📋 Instructions ({instructions.filter(i => i.is_active).length})
              </button>
            </div>
          </div>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Main Chat Area */}
          <div className="lg:col-span-3">
            <div className="bg-white rounded-2xl shadow-lg border border-gray-200 h-96 lg:h-[700px] overflow-hidden">
              <Chat
                onInstructionsClick={() => setShowInstructions(true)}
                onSearchResults={handleSearchResults}
              />
            </div>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Connections */}
            {connections && (
              <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6">
                <ConnectionBadges
                  connections={connections}
                  onGoogleConnect={handleGoogleConnect}
                  onHubSpotConnect={handleHubSpotConnect}
                />
              </div>
            )}

            {/* Ongoing Tasks */}
            <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-4">Ongoing Tasks</h3>
              <div className="space-y-3">
                {tasks.filter(t => t.status === 'waiting' || t.status === 'pending').map((task) => (
                  <div key={task.id} className="p-4 bg-yellow-50 rounded-xl border border-yellow-200 hover:bg-yellow-100 transition-colors">
                    <p className="text-sm font-medium text-gray-900">{task.title}</p>
                    <p className="text-xs text-yellow-700 capitalize mt-1">{task.status}</p>
                  </div>
                ))}
                {tasks.filter(t => t.status === 'waiting' || t.status === 'pending').length === 0 && (
                  <div className="text-center py-8">
                    <div className="w-12 h-12 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-3">
                      <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                      </svg>
                    </div>
                    <p className="text-sm text-gray-500">No ongoing tasks</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Instructions Modal */}
      {showInstructions && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-3xl w-full max-h-[80vh] overflow-hidden shadow-2xl">
            <div className="p-8 max-h-[80vh] overflow-y-auto">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold text-gray-900">Ongoing Instructions</h2>
                <button
                  onClick={() => setShowInstructions(false)}
                  className="text-gray-400 hover:text-gray-600 transition-colors p-2 hover:bg-gray-100 rounded-full"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Add New Instruction */}
              <div className="mb-8">
                <label className="block text-sm font-medium text-gray-700 mb-3">Add New Instruction</label>
                <textarea
                  value={newInstruction}
                  onChange={(e) => setNewInstruction(e.target.value)}
                  placeholder="Add a new ongoing instruction..."
                  className="w-full p-4 border border-gray-300 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
                  rows={3}
                />
                <button
                  onClick={handleCreateInstruction}
                  className="mt-3 px-6 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors font-medium"
                >
                  Add Instruction
                </button>
              </div>

              {/* Existing Instructions */}
              <div className="space-y-4 max-h-96 overflow-y-auto">
                {instructions.map((instruction) => (
                  <div key={instruction.id} className="p-4 border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors">
                    <div className="flex justify-between items-start">
                      <p className="text-sm flex-1 text-gray-900 leading-relaxed">{instruction.content}</p>
                      <button
                        onClick={() => handleToggleInstruction(instruction.id, instruction.is_active)}
                        className={`ml-4 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                          instruction.is_active
                            ? 'bg-green-100 text-green-700 hover:bg-green-200'
                            : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                        }`}
                      >
                        {instruction.is_active ? 'Active' : 'Inactive'}
                      </button>
                    </div>
                    <p className="text-xs text-gray-500 mt-2">
                      Created: {new Date(instruction.created_at).toLocaleDateString()}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Search Results Modal */}
      {showSearchResults && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-5xl w-full max-h-[85vh] overflow-hidden shadow-2xl">
            <div className="p-8">
              <div className="flex justify-between items-center mb-6">
                <h2 className="text-2xl font-bold text-gray-900">Search Results</h2>
                <button
                  onClick={() => setShowSearchResults(false)}
                  className="text-gray-400 hover:text-gray-600 transition-colors p-2 hover:bg-gray-100 rounded-full"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>

              <div className="space-y-4 max-h-[60vh] overflow-y-auto">
                {searchResults.map((result, index) => (
                  <div key={index} className="border border-gray-200 rounded-xl p-6 hover:bg-gray-50 transition-colors">
                    <div className="flex items-start justify-between mb-3">
                      <h3 className="font-semibold text-gray-900 text-lg">{result.title || result.subject || 'Search Result'}</h3>
                      <span className="text-sm text-gray-500 bg-gray-100 px-3 py-1 rounded-full">{result.source || 'Unknown'}</span>
                    </div>
                    <p className="text-gray-700 mb-3 leading-relaxed">{result.content || result.snippet || result.body}</p>
                    <div className="flex items-center space-x-4 text-sm text-gray-500">
                      {result.contact_email && (
                        <span>📧 From: {result.contact_email}</span>
                      )}
                      {result.date && (
                        <span>📅 {new Date(result.date).toLocaleDateString()}</span>
                      )}
                    </div>
                  </div>
                ))}
                {searchResults.length === 0 && (
                  <div className="text-center py-12">
                    <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                      <svg className="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                      </svg>
                    </div>
                    <p className="text-gray-500 text-lg">No search results found</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Dashboard;
