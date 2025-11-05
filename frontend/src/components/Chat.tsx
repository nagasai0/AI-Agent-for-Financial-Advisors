import React, { useState, useRef, useEffect } from 'react';
import { apiClient, WebSocketMessage } from '../lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  timestamp: Date;
  tool_calls?: any[];
  isStreaming?: boolean;
  toolCallStatus?: 'executing' | 'completed' | 'failed';
}

interface ChatProps {
  onInstructionsClick: () => void;
  onSearchResults: (results: any[]) => void;
}

const Chat: React.FC<ChatProps> = ({ onInstructionsClick, onSearchResults }) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [currentUser, setCurrentUser] = useState<any>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Initialize user and WebSocket - only once
  useEffect(() => {
    let mounted = true;
    
    const initUser = async () => {
      try {
        const user = await apiClient.getCurrentUser();
        if (!mounted) return;
        setCurrentUser(user);
        
        // Initialize WebSocket connection after user is loaded
        if (!wsRef.current) {
          initializeWebSocket(user.id);
        }
      } catch (error) {
        console.error('Failed to get current user:', error);
      }
    };

    initUser();

    return () => {
      mounted = false;
      // Keep WebSocket open for reuse across messages
    };
  }, []); // Empty dependency array - only run once

  const initializeWebSocket = (userId: string) => {
    if (wsRef.current) {
      console.log('WebSocket already exists, reusing connection');
      return;
    }

    console.log('Initializing WebSocket connection...');
    const ws = new WebSocket(`wss://learn-jump.onrender.com/ws/chat?user_id=${userId}`);
    
    ws.onopen = () => {
      console.log('WebSocket connected');
    };
    
    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        handleWebSocketMessage(message);
      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    };
    
    ws.onclose = () => {
      console.log('WebSocket disconnected');
      wsRef.current = null;
    };
    
    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
    
    wsRef.current = ws;
  };

  const handleWebSocketMessage = (message: WebSocketMessage) => {
    console.log('WebSocket message received:', message);

    switch (message.type) {
      case 'chat_history':
        // Load chat history on initial connection
        if (message.messages && Array.isArray(message.messages)) {
          const historyMessages = message.messages
            .filter((msg: any) => {
              // Filter out proactive evaluation messages and empty content
              return msg.content && 
                     msg.content.trim() !== "" && 
                     !msg.content.startsWith("PROACTIVE EVENT EVALUATION");
            })
            .map((msg: any, index: number) => ({
              id: `history-${index}-${Date.now()}`,
              role: msg.role,
              content: msg.content,
              timestamp: new Date(),
              isStreaming: false
            }));
          setMessages(historyMessages);
        }
        break;

      case 'assistant_start':
        // Filter out proactive evaluation messages
        if (message.content && !message.content.startsWith("PROACTIVE EVENT EVALUATION")) {
          setMessages(prev => [...prev, {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: message.content || 'Thinking...',
            timestamp: new Date(),
            isStreaming: true
          }]);
        }
        break;

      case 'tool_calls_start':
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.isStreaming) {
            return [...prev.slice(0, -1), {
              ...lastMessage,
              content: message.content || 'Executing tools...',
              tool_calls: []
            }];
          }
          return prev;
        });
        break;

      case 'tool_call':
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.isStreaming) {
            const newToolCall = {
              tool: message.tool || '',
              arguments: message.arguments || {},
              result: null,
              status: 'executing'
            };
            
            return [...prev.slice(0, -1), {
              ...lastMessage,
              tool_calls: [...(lastMessage.tool_calls || []), newToolCall]
            }];
          }
          return prev;
        });
        break;

      case 'tool_result':
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.tool_calls) {
            const updatedToolCalls = lastMessage.tool_calls.map(tc => 
              tc.tool === message.tool ? { ...tc, result: message.result, status: 'completed' } : tc
            );
            
            return [...prev.slice(0, -1), {
              ...lastMessage,
              tool_calls: updatedToolCalls
            }];
          }
          return prev;
        });
        break;

      case 'tool_calls_complete':
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.isStreaming) {
            return [...prev.slice(0, -1), {
              ...lastMessage,
              content: message.content || 'Processing results...'
            }];
          }
          return prev;
        });
        break;

      case 'assistant_response':
        // Filter out proactive evaluation messages
        if (message.content && !message.content.startsWith("PROACTIVE EVENT EVALUATION")) {
          setMessages(prev => {
            const lastMessage = prev[prev.length - 1];
            if (lastMessage && lastMessage.isStreaming) {
              return [...prev.slice(0, -1), {
                ...lastMessage,
                content: message.content || '',
                isStreaming: false,
                tool_calls: message.tool_calls || lastMessage.tool_calls
              }];
            }
            return prev;
          });
        }
        setIsLoading(false);
        // Keep WebSocket open for next message
        break;

      case 'error':
        setMessages(prev => {
          const lastMessage = prev[prev.length - 1];
          if (lastMessage && lastMessage.isStreaming) {
            return [...prev.slice(0, -1), {
              ...lastMessage,
              content: message.content || 'An error occurred',
              isStreaming: false
            }];
          }
          return prev;
        });
        setIsLoading(false);
        // Keep WebSocket open for next message
        break;
    }
  };

  const handleSend = async () => {
    if (!input.trim() || isLoading || !currentUser) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    const messageToSend = input;
    setInput('');
    setIsLoading(true);

    try {
      // Use existing WebSocket connection
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        console.log('Sending message via existing WebSocket connection');
        wsRef.current.send(JSON.stringify({ message: messageToSend }));
      } else {
        console.error('No WebSocket connection available');
        setIsLoading(false);
        
        // Fallback to HTTP API
        apiClient.sendMessage(messageToSend).then((response: any) => {
          const assistantMessage: Message = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: response.response,
            timestamp: new Date(),
            tool_calls: response.tool_calls,
          };
          setMessages(prev => [...prev, assistantMessage]);
          setIsLoading(false);
        }).catch((err: any) => {
          console.error('HTTP API error:', err);
          const errorMessage: Message = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: 'Sorry, I encountered an error. Please try again.',
            timestamp: new Date(),
          };
          setMessages(prev => [...prev, errorMessage]);
          setIsLoading(false);
        });
      }
      
    } catch (error) {
      console.error('Send error:', error);
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleQuickAction = (action: string) => {
    if (action === '/instructions') {
      onInstructionsClick();
    }
  };

  const handleClearHistory = async () => {
    if (!confirm('Are you sure you want to clear all chat history? This cannot be undone.')) {
      return;
    }

    try {
      const result = await apiClient.clearChatHistory();
      setMessages([]);
      alert(`Successfully cleared ${result.deleted_count} messages`);
    } catch (error) {
      console.error('Failed to clear history:', error);
      alert('Failed to clear chat history');
    }
  };

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-gray-900">Ask Anything</h2>
            <p className="text-sm text-gray-500 mt-0.5">Your AI Financial Advisor Assistant</p>
          </div>
          {messages.length > 0 && (
            <button
              onClick={handleClearHistory}
              className="px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors"
            >
              Clear History
            </button>
          )}
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6">
        {messages.length === 0 && (
          <div className="max-w-3xl mx-auto">
            <div className="text-center mb-8">
              <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center mx-auto mb-4 shadow-lg">
                <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
              <h3 className="text-2xl font-semibold text-gray-900 mb-2">Welcome to your AI Assistant</h3>
              <p className="text-gray-600 text-lg">
                I can help you manage your clients, schedule appointments, send emails, and search through your communications.
              </p>
            </div>
          </div>
        )}

        <div className="max-w-3xl mx-auto space-y-6">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex items-start gap-4 ${message.role === 'user' ? 'justify-end' : ''}`}
            >
              {/* Avatar */}
              {message.role === 'user' ? (
                <div className="flex-shrink-0 w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center order-2">
                  <svg className="w-5 h-5 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
              ) : (
                <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                </div>
              )}
              
              <div className={`${message.role === 'user' ? 'flex-1 min-w-0 order-1 flex flex-col items-end' : 'flex-1 min-w-0'}`}>
                <div
                  className={`inline-block max-w-full px-4 py-3 rounded-2xl ${
                    message.role === 'user'
                      ? 'bg-blue-600 text-white'
                      : message.role === 'tool'
                      ? 'bg-amber-50 text-amber-900 border border-amber-200'
                      : 'bg-gray-100 text-gray-900'
                  }`}
                >
                  <div className="text-sm leading-relaxed whitespace-pre-wrap break-words">{message.content}</div>
                  {message.tool_calls && message.tool_calls.length > 0 && (
                    <div className="mt-3 pt-3 border-t border-gray-300">
                      <div className="text-xs font-medium text-gray-600 mb-2">🔧 Tools Used:</div>
                      <div className="space-y-2">
                        {message.tool_calls.map((tc, idx) => (
                          <div key={idx} className="bg-white border border-gray-200 rounded-md p-2 text-xs">
                            <div className="flex items-center justify-between mb-2">
                              <div className="font-medium text-gray-700">{tc.tool}</div>
                              <div className="flex items-center space-x-2">
                                {tc.status === 'executing' && (
                                  <div className="flex items-center space-x-1">
                                    <div className="animate-spin rounded-full h-3 w-3 border-b border-blue-600"></div>
                                    <span className="text-blue-600 text-xs">Executing...</span>
                                  </div>
                                )}
                                {tc.status === 'completed' && tc.result && (
                                  <div className="text-gray-600">
                                    {tc.result.success ? (
                                      <span className="text-green-600">✓ Success</span>
                                    ) : (
                                      <span className="text-red-600">✗ Failed</span>
                                    )}
                                    {tc.result.count !== undefined && (
                                      <span className="ml-2">({tc.result.count} results)</span>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                            {/* Show tool result details */}
                            {tc.status === 'completed' && tc.result && tc.result.success && (
                              <div className="mt-2 pt-2 border-t border-gray-100">
                                {tc.result.message && (
                                  <div className="text-gray-600 text-xs mb-1">{tc.result.message}</div>
                                )}
                                {tc.result.emails && tc.result.emails.length > 0 && (
                                  <div className="space-y-1">
                                    {tc.result.emails.slice(0, 3).map((email: any, i: number) => (
                                      <div key={i} className="text-gray-500 text-xs truncate">
                                        📧 {email.subject || 'No subject'}
                                        {email.contact_email && <span className="ml-1 text-gray-400">from {email.contact_email}</span>}
                                      </div>
                                    ))}
                                    {tc.result.emails.length > 3 && (
                                      <div className="text-gray-400 text-xs">+{tc.result.emails.length - 3} more</div>
                                    )}
                                  </div>
                                )}
                                {tc.result.notes && tc.result.notes.length > 0 && (
                                  <div className="space-y-1">
                                    {tc.result.notes.slice(0, 3).map((note: any, i: number) => (
                                      <div key={i} className="text-gray-500 text-xs truncate">
                                        📝 {note.snippet || note.content}
                                      </div>
                                    ))}
                                    {tc.result.notes.length > 3 && (
                                      <div className="text-gray-400 text-xs">+{tc.result.notes.length - 3} more</div>
                                    )}
                                  </div>
                                )}
                                {(tc.result.emails || tc.result.notes) && (
                                  <button
                                    onClick={() => {
                                      const allResults = [...(tc.result.emails || []), ...(tc.result.notes || [])];
                                      onSearchResults(allResults);
                                    }}
                                    className="mt-2 px-2 py-1 text-xs bg-blue-50 text-blue-700 rounded hover:bg-blue-100 transition-colors border border-blue-200"
                                  >
                                    🔍 View All Results
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <div className={`text-xs mt-2 px-1 ${
                  message.role === 'user' ? 'text-right text-gray-400' : 'text-gray-400'
                }`}>
                  {message.timestamp.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                </div>
              </div>
            </div>
          ))}

          {isLoading && !messages.some(m => m.isStreaming) && (
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-8 h-8 bg-gradient-to-br from-blue-500 to-purple-600 rounded-full flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              </div>
              <div className="bg-gray-100 text-gray-800 px-4 py-3 rounded-2xl">
                <div className="flex items-center space-x-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
                  <span className="text-sm">Connecting...</span>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 bg-white px-4 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-3">
            <div className="flex-1">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Ask anything about your clients, emails, or calendar..."
                className="w-full px-4 py-3 border border-gray-300 rounded-2xl resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all text-sm"
                rows={1}
                disabled={isLoading}
                style={{ minHeight: '48px', maxHeight: '120px' }}
              />
            </div>
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className="px-4 py-3 bg-blue-600 text-white rounded-2xl hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center shadow-sm"
              style={{ minWidth: '48px', minHeight: '48px' }}
            >
              {isLoading ? (
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </div>
          
          {/* Quick Actions */}
          <div className="flex space-x-2 mt-3">
            <button
              onClick={() => handleQuickAction('/instructions')}
              className="px-3 py-1.5 text-xs bg-blue-50 text-blue-700 rounded-lg hover:bg-blue-100 transition-colors border border-blue-200"
            >
              📋 /instructions
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Chat;
